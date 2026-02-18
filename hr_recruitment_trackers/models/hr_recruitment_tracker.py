# -*- coding: utf-8 -*-
import random
import string
import werkzeug.urls
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class HrRecruitmentTrackerParam(models.Model):
    _name = 'hr.recruitment.tracker.param'
    _description = 'Recruitment Tracker Parameter'

    tracker_id = fields.Many2one('hr.recruitment.tracker', string='Tracker', required=True, ondelete='cascade')
    # Many2one for Key
    key_id = fields.Many2one('hr.tracking.param.key', string='Key', required=True)
    # Many2one for Value, strictly filtered by Key
    value_id = fields.Many2one('hr.tracking.param.value', string='Value', required=True, domain="[('key_id', '=', key_id)]")


class HrRecruitmentTracker(models.Model):
    _name = 'hr.recruitment.tracker'
    _description = 'Recruitment Link Tracker'
    _inherit = ['utm.mixin']
    _rec_name = 'name'
    _order = 'create_date desc'

    name = fields.Char(string='Name', required=True, default=lambda self: _("New Token"))
    
    token = fields.Char(string='Token', required=True, copy=False, default=lambda self: self._get_random_token())
    target_url = fields.Char(string='Target URL', required=True, help="The final URL where the candidate should be redirected.")
    public_url = fields.Char(string='Public URL', compute='_compute_public_url', help="The shortened URL to share.")
    
    job_id = fields.Many2one('hr.job', string='Job Position', required=True, ondelete='cascade')
    company_id = fields.Many2one('res.company', string='Company', related='job_id.company_id', store=True)
    
    active = fields.Boolean(default=True)
    expires_at = fields.Datetime(string='Expires At', help="If set, the link will not work after this date.")
    max_uses = fields.Integer(string='Max Uses', default=0, help="Maximum number of clicks allowed. 0 means unlimited.")
    
    # Custom Logic
    param_ids = fields.One2many('hr.recruitment.tracker.param', 'tracker_id', string='Custom Parameters')

    use_count = fields.Integer(string='Use Count', default=0, readonly=True)
    last_used_at = fields.Datetime(string='Last Used At', readonly=True)
    last_used_ip = fields.Char(string='Last Used IP', readonly=True)
    last_used_user_agent = fields.Char(string='Last Used User Agent', readonly=True)

    _sql_constraints = [
        ('token_uniq', 'unique(token)', 'The token must be unique!'),
    ]

    @api.model
    def _get_random_token(self, size=8):
        chars = string.ascii_letters + string.digits
        return ''.join(random.choice(chars) for _ in range(size))

    @api.depends('token')
    def _compute_public_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for record in self:
            if record.token:
                record.public_url = werkzeug.urls.url_join(base_url, f'/t/{record.token}')
            else:
                record.public_url = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'token' not in vals:
                vals['token'] = self._get_random_token()
        return super().create(vals_list)

    @api.onchange('job_id')
    def _onchange_job_id(self):
        if self.job_id:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            slug = self.job_id.name.lower().replace(' ', '-')
            self.target_url = werkzeug.urls.url_join(base_url, f"/jobs/{slug}-{self.job_id.id}")

    def action_copy_url(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Link Copied'),
                'message': _('The link has been copied to clipboard.'),
                'type': 'success',
                'sticky': False,
            }
        }