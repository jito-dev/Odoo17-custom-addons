from odoo import models, fields, api
import uuid

class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    iq_score = fields.Integer("Cognitive Assessment Result", readonly=True)
    iq_category = fields.Char("Cognitive Category", readonly=True)
    iq_access_token = fields.Char("Cognitive Access Token", copy=False, default=lambda self: str(uuid.uuid4()))
    iq_input_id = fields.Many2one('iq.user_input', string="Cognitive Assessment Record")

    def _get_iq_test_url(self):
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        survey = self.job_id.iq_survey_id
        if not survey: return "#"
        return f"{base_url}/iq-test/go/{survey.slug}?token={self.iq_access_token}"