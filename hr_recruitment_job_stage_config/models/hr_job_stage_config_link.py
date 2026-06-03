# -*- coding: utf-8 -*-
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrJobStageConfigLink(models.Model):
    _name = 'hr.job.stage.config.link'
    _description = 'Per-(job × stage) named URL resource'
    _order = 'sequence, id'

    config_id = fields.Many2one(
        'hr.job.stage.config', string='Stage configuration',
        required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    label = fields.Char(string='Label', required=True,
                       help="Human-readable name (e.g. 'Git repository', "
                            "'Specification', 'Sample data').")
    url = fields.Char(string='URL', required=True,
                     help='Must start with http:// or https://.')

    @api.constrains('url')
    def _check_url_scheme(self):
        pattern = re.compile(r'^https?://', re.IGNORECASE)
        for link in self:
            if not pattern.match(link.url or ''):
                raise ValidationError(_(
                    "Link URL '%s' must start with http:// or https://.",
                    link.url,
                ))
