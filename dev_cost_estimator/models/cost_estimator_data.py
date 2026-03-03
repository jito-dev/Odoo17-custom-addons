# -*- coding: utf-8 -*-
import requests
import re
import json
import math
import random
from odoo import models, fields
from odoo.exceptions import UserError




class CostEstimatorData(models.Model):
    _name = "cost.estimator.data"
    _description = "Cost estimator data"

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

    avg_min = fields.Integer(string="Avg Min Salary")
    avg_max = fields.Integer(string="Avg Max Salary")
    online_count = fields.Integer(string="Candidates Online")
    cached_at = fields.Datetime(string="Cached At", readonly=True)
    chart_data_json = fields.Text(string="Chart Data")

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
