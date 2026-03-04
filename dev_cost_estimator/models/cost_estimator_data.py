# -*- coding: utf-8 -*-
import requests
import re
import json
import math
import random
from odoo import api, models, fields
from odoo.exceptions import UserError


class CostEstimatorData(models.Model):
    _name = "cost.estimator.data"
    _description = "Cost estimator data"

    enabled_category_ids = fields.Many2many(
        'cost.estimator.category',
        'cost_estimator_data_cat_rel',
        'data_id',
        'cat_id',
        string='Active Categories',
    )

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        if 'enabled_category_ids' in fields_list:
            all_cats = self.env['cost.estimator.category'].search([])
            defaults['enabled_category_ids'] = [(6, 0, all_cats.ids)]
        return defaults

    category_id = fields.Many2one(
        "cost.estimator.category",
        string="Category",
        required=False,
    )
    exp = fields.Selection([
        ('any', 'Any'),
        ('0', '< 1 year'),
        ('1', '1-2 years'),
        ('2', '2-3 years'),
        ('3', '3-5 years'),
        ('5', '5+ years')
    ], string='Years of experience', default='any')
    multiplier = fields.Selection([
        ('default', 'x1'),
        ('1.2', 'x1.2'),
        ('1.25', 'x1.25'),
        ('1.3', 'x1.3'),
        ('1.4', 'x1.4'),
        ('1.5', 'x1.5'),
        ('2', 'x2'),
        ('3', 'x3'),
    ], string='Multiplier', default='default')

    avg_min = fields.Integer(string="Avg Min Salary")
    avg_max = fields.Integer(string="Avg Max Salary")
    online_count = fields.Integer(string="Candidates Online")
    cached_at = fields.Datetime(string="Cached At", readonly=True)
    chart_data_json = fields.Text(string="Chart Data")

    salary_display_monthly = fields.Char(compute='_compute_salary_displays')
    salary_display_hourly = fields.Char(compute='_compute_salary_displays')
    salary_display_daily = fields.Char(compute='_compute_salary_displays')
    chart_display_json = fields.Text(compute='_compute_chart_display_json')

    def _round_salary(self, value):
        base = int(value)
        decimal = value - base
        if decimal >= 0.5:
            return float(base + 1)
        return float(base + 0.5)

    def _format_val(self, val, unit=""):
        formatted = f"{val:g}" 
        if ".5" in formatted and unit == "$/h":
            formatted = f"{val:.2f}"
            
        if unit == "$":
            return f"${formatted}"
        return f"{formatted} {unit}" 

    @api.depends('avg_min', 'avg_max', 'multiplier')
    def _compute_salary_displays(self):
        for rec in self:
            m = 1.0 if not rec.multiplier or rec.multiplier == 'default' else float(rec.multiplier)
            
            raw_mn = (rec.avg_min or 0) * m
            raw_mx = (rec.avg_max or 0) * m
            
            if raw_mn or raw_mx:
                mn_m = int(self._round_salary(raw_mn))
                mx_m = int(self._round_salary(raw_mx))
                rec.salary_display_monthly = f"{self._format_val(mn_m, '$')} – {self._format_val(mx_m, '$')}"

                mn_h = self._round_salary(raw_mn / 160)
                mx_h = self._round_salary(raw_mx / 160)
                rec.salary_display_hourly = f"{self._format_val(mn_h, '$/h')} – {self._format_val(mx_h, '$/h')}"

                mn_d = int(self._round_salary(raw_mn / 20))
                mx_d = int(self._round_salary(raw_mx / 20))
                rec.salary_display_daily = f"{self._format_val(mn_d, '$/day')} – {self._format_val(mx_d, '$/day')}"
            else:
                rec.salary_display_monthly = rec.salary_display_hourly = rec.salary_display_daily = False

    @api.depends('chart_data_json', 'multiplier')
    def _compute_chart_display_json(self):
        for rec in self:
            if not rec.chart_data_json:
                rec.chart_display_json = False
                continue
            m = 1.0 if not rec.multiplier or rec.multiplier == 'default' else float(rec.multiplier)
            if m == 1.0:
                rec.chart_display_json = rec.chart_data_json
                continue
            try:
                data = json.loads(rec.chart_data_json)
                scaled = dict(data)
                scaled['avg_min'] = int(data.get('avg_min', 0) * m)
                scaled['avg_max'] = int(data.get('avg_max', 0) * m)
                scaled['points'] = [
                    dict(pt,
                         salary_min=int(pt.get('salary_min', 0) * m),
                         salary_max=int(pt.get('salary_max', 0) * m))
                    for pt in data.get('points', [])
                ]
                rec.chart_display_json = json.dumps(scaled)
            except Exception:
                rec.chart_display_json = rec.chart_data_json

    @api.onchange('category_id')
    def _onchange_category_id(self):
        if self.category_id:
            config = self.env['cost.estimator.admin.config'].search(
                [('category', '=', self.category_id.name)], limit=1
            )
            self.multiplier = config.multiplier if config and config.multiplier else 'default'
        else:
            self.multiplier = 'default'

    def _get_category_slug(self):
        if not self.category_id:
            return None
        ext_ids = self.category_id.get_external_id()
        xml_id_full = ext_ids.get(self.category_id.id)
        if xml_id_full:
            return xml_id_full.split('.')[-1]
        return re.sub(r'[^a-zA-Z0-9]+', '-', self.category_id.name.lower()).strip('-')

    def _extract_chart_data(self, html):
        """Extract chartData, avgRange, and onlineCount from Djinni HTML.

        Mirrors the JS reference: iterates <script type="module"> blocks,
        finds the one that contains JSON.parse / avgRange / candidatesOnlineCount,
        then extracts all three values with the same regex patterns.
        """
        script_blocks = re.findall(
            r'<script[^>]+type=["\']module["\'][^>]*>(.*?)</script>',
            html,
            re.DOTALL | re.IGNORECASE,
        )

        for script in script_blocks:
            if 'JSON.parse' not in script:
                continue
            if 'avgRange' not in script:
                continue
            if 'candidatesOnlineCount' not in script:
                continue

            chart_data = None
            avg_range = None
            online_count = 0

            m = re.search(r"const data = JSON\.parse\('(.*)'\)", script)
            if m:
                try:
                    chart_data = json.loads(m.group(1))
                except Exception:
                    pass

            m = re.search(r'const avgRange =(\[.*?\])', script)
            if m:
                try:
                    avg_range = json.loads(m.group(1))
                except Exception:
                    pass

            m = re.search(r'const candidatesOnlineCount = (\d+)', script)
            if m:
                online_count = int(m.group(1))

            if chart_data is not None:
                return chart_data, avg_range or [0, 0], online_count

        return None, [0, 0], 0

    def _parse_histogram_points(self, raw):
        if not raw:
            return []
        points = []
        for item in raw:
            if isinstance(item, dict) and 'salary_min' in item and 'count' in item:
                salary_min = int(item['salary_min'])
                salary_max = int(item.get('salary_max', salary_min + 1000))
                count = int(item['count'])
                points.append({'salary_min': salary_min, 'salary_max': salary_max, 'candidate_count': count})
            elif isinstance(item, dict) and 'x' in item and 'y' in item:
                salary = int(item['x'])
                points.append({'salary_min': salary, 'salary_max': salary + 1000, 'candidate_count': int(item['y'])})
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                salary = int(item[0])
                points.append({'salary_min': salary, 'salary_max': salary + 1000, 'candidate_count': int(item[1])})
            else:
                continue
        return points

    def _synthetic_points(self, avg_min, avg_max, total_candidates):
        avg_min = int(avg_min or 0)
        avg_max = int(avg_max or 0)
        if avg_min == 0 and avg_max == 0:
            return []
        if total_candidates == 0:
            total_candidates = 100

        # Bins matching the Djinni API histogram format
        bins = [
            {'salary_min': 0,     'salary_max': 500},
            {'salary_min': 500,   'salary_max': 1000},
            {'salary_min': 1000,  'salary_max': 2000},
            {'salary_min': 2000,  'salary_max': 3000},
            {'salary_min': 3000,  'salary_max': 4000},
            {'salary_min': 4000,  'salary_max': 5000},
            {'salary_min': 5000,  'salary_max': 6000},
            {'salary_min': 6000,  'salary_max': 7000},
            {'salary_min': 7000,  'salary_max': 8000},
            {'salary_min': 8000,  'salary_max': 9000},
            {'salary_min': 9000,  'salary_max': 10000},
            {'salary_min': 10000, 'salary_max': 15000},
        ]

        center = (avg_min + avg_max) / 2
        sigma = max((avg_max - avg_min) / 2.0, 800)
        skew_factor = random.uniform(0.9, 1.1)

        weights = []
        total_weight = 0
        for b in bins:
            mid = (b['salary_min'] + b['salary_max']) / 2
            z = (mid - center) / sigma
            w = math.exp(-0.5 * (z * skew_factor) ** 2) * random.uniform(0.85, 1.15)
            weights.append(w)
            total_weight += w

        if total_weight == 0:
            total_weight = 1

        remaining = total_candidates
        points = []
        for i, (b, w) in enumerate(zip(bins, weights)):
            if i == len(bins) - 1:
                count = remaining
            else:
                count = int(round((w / total_weight) * total_candidates))
                remaining -= count
            if count > 0:
                points.append({
                    'salary_min': b['salary_min'],
                    'salary_max': b['salary_max'],
                    'candidate_count': count,
                })

        return points

    def _fetch_from_api(self):
        params = {'english_level': 'upper', 'region': 'UKR'}
        slug = self._get_category_slug()
        if slug:
            params['category'] = slug
        if self.exp and self.exp != 'any':
            params['exp'] = self.exp

        try:
            response = requests.get("https://djinni.co/salaries/", params=params, timeout=10)
            response.raise_for_status()
            html = response.text
        except Exception:
            return {'avg_min': 2000, 'avg_max': 4000, 'online_count': 0, 'points': []}

        chart_data, avg_range, online_count = self._extract_chart_data(html)
        points = self._parse_histogram_points(chart_data)

        avg_min = int(avg_range[0] or 0) if avg_range and len(avg_range) > 0 else 0
        avg_max = int(avg_range[1] or 0) if avg_range and len(avg_range) > 1 else 0

        if not points:
            points = self._synthetic_points(avg_min, avg_max, online_count)

        return {'avg_min': avg_min, 'avg_max': avg_max, 'online_count': online_count, 'points': points}

    def _load_from_cache(self):
        cache = self.env['cost.estimator.cache'].search([
            ('category_id', '=', self.category_id.id if self.category_id else False),
            ('exp', '=', self.exp or 'any'),
        ], limit=1)
        if not cache or not cache.is_fresh():
            return False

        points = []
        if cache.chart_data:
            try:
                points = json.loads(cache.chart_data)
            except:
                pass
        if not points:
            points = self._synthetic_points(cache.avg_min, cache.avg_max, cache.online_count)

        self._write_result(cache.avg_min, cache.avg_max, cache.online_count, points, cached_at=cache.cached_at)
        return True

    def _save_to_cache(self, values):
        cache = self.env['cost.estimator.cache'].search([
            ('category_id', '=', self.category_id.id if self.category_id else False),
            ('exp', '=', self.exp or 'any'),
        ], limit=1)

        points_json = False
        if values.get('points'):
            points_json = json.dumps(values['points'])

        vals = {
            'avg_min': values['avg_min'],
            'avg_max': values['avg_max'],
            'online_count': values['online_count'],
            'chart_data': points_json,
            'cached_at': fields.Datetime.now(),
        }
        if cache:
            cache.write(vals)
        else:
            vals.update({
                'category_id': self.category_id.id if self.category_id else False,
                'exp': self.exp or 'any',
            })
            self.env['cost.estimator.cache'].create(vals)

    def _write_result(self, avg_min, avg_max, online_count, points, cached_at=None):
        chart_json = False
        if points and isinstance(points, list):
            chart_json = json.dumps({
                'avg_min': avg_min,
                'avg_max': avg_max,
                'online_count': online_count,
                'points': [
                    {
                        'salary_min': pt.get('salary_min', pt.get('salary', 0)),
                        'salary_max': pt.get('salary_max', pt.get('salary', 0) + 1000),
                        'count': pt['candidate_count'],
                    }
                    for pt in points
                ],
            })
        self.write({
            'avg_min': avg_min,
            'avg_max': avg_max,
            'online_count': online_count,
            'cached_at': cached_at or fields.Datetime.now(),
            'chart_data_json': chart_json,
        })

    # Actions
    def action_find_estimate(self):
        self.ensure_one()
        if not self.enabled_category_ids:
            all_cats = self.env['cost.estimator.category'].search([])
            self.write({'enabled_category_ids': [(6, 0, all_cats.ids)]})
        if self._load_from_cache():
            return False

        try:
            data = self._fetch_from_api()
        except Exception as e:
            raise UserError(f"Error fetching data: {str(e)}")

        self._save_to_cache(data)
        self._write_result(data['avg_min'], data['avg_max'], data['online_count'], data['points'])
        return False

    def action_force_refresh(self):
        self.ensure_one()
        try:
            data = self._fetch_from_api()
        except Exception as e:
            raise UserError(f"Error fetching data: {str(e)}")

        self._save_to_cache(data)
        self._write_result(data['avg_min'], data['avg_max'], data['online_count'], data['points'])
        return False
