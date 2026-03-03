# -*- coding: utf-8 -*-
import requests
import re
import json
import math
import random
from odoo import models, fields
from odoo.exceptions import UserError


_CHART_DATA_PATTERNS = [
    r"const data = JSON\.parse\('(.*?)'\)",
    r"var data = JSON\.parse\('(.*?)'\)",
    r"let data = JSON\.parse\('(.*?)'\)",
    r"\"data\":JSON\.parse\('(.*?)'\)",
    r"data:\s*JSON\.parse\('(.*?)'\)",
]


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

    def _extract_raw_points(self, html):
        for pattern in _CHART_DATA_PATTERNS:
            m = re.search(pattern, html)
            if m:
                try:
                    raw_str = m.group(1).encode().decode('unicode_escape')
                    return json.loads(raw_str)
                except:
                    continue
        return None

    def _parse_histogram_points(self, raw):
        if not raw:
            return []
        points = []
        for item in raw:
            if isinstance(item, dict) and 'x' in item and 'y' in item:
                salary, count = item['x'], item['y']
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                salary, count = item[0], item[1]
            else:
                continue
            points.append({'salary': int(salary), 'candidate_count': int(count)})
        return points

    def _synthetic_points(self, avg_min, avg_max, total_candidates):
        if avg_min == 0 and avg_max == 0:
            return []
        if total_candidates == 0:
            total_candidates = 100

        center = (avg_min + avg_max) / 2
        sigma = max((avg_max - avg_min) / 2.0, 800)

        skew_factor = random.uniform(0.9, 1.1)
        total_weight = 0
        temp_points = []

        start_range = max(500, int(center - 3 * sigma))
        end_range = int(center + 3 * sigma)

        for sal in range(start_range, end_range, 100):
            z = (sal - center) / sigma
            weight = math.exp(-0.5 * (z * skew_factor) ** 2)
            noise = random.uniform(0.85, 1.15)
            weight *= noise
            if weight > 0.01:
                temp_points.append({'salary': sal, 'weight': weight})
                total_weight += weight

        if total_weight == 0:
            total_weight = 1

        remaining_candidates = total_candidates
        points = []
        for i, p in enumerate(temp_points):
            if i == len(temp_points) - 1:
                count = remaining_candidates
            else:
                count = int(round((p['weight'] / total_weight) * total_candidates))
                remaining_candidates -= count
            if count > 0:
                points.append({'salary': p['salary'], 'candidate_count': count})

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

        raw = self._extract_raw_points(html)
        points = self._parse_histogram_points(raw)

        avg_range = [0, 0]
        m = re.search(r"const avgRange\s*=\s*(\[.*?\])", html)
        if m:
            try:
                avg_range = json.loads(m.group(1))
            except:
                pass

        online_count = 0
        m2 = re.search(r"const candidatesOnlineCount\s*=\s*(\d+)", html)
        if m2:
            online_count = int(m2.group(1))

        avg_min = avg_range[0] if len(avg_range) > 0 else 0
        avg_max = avg_range[1] if len(avg_range) > 1 else 0

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
                'points': [
                    {'salary': pt['salary'], 'count': pt['candidate_count']}
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
