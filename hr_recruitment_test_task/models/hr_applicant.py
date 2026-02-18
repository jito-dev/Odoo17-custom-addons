from odoo import models, fields, api
import uuid

class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    # Security & Access
    test_task_token = fields.Char("Test Task Token", default=lambda self: str(uuid.uuid4()), copy=False, readonly=True)
    
    # Submission Data
    submission_ids = fields.One2many('hr.test.submission', 'applicant_id', string="Submissions")
    
    # Helper to show the latest link in the main form view comfortably
    last_github_link = fields.Char(related='submission_ids.github_link', store=True, readonly=True, string="Latest GitHub Link")
    
    # AI Analysis Results
    ai_analysis_score = fields.Integer("AI Score", readonly=True)
    ai_analysis_summary = fields.Html("AI Feedback", readonly=True)

    # Related field to control visibility based on Job configuration
    job_add_test_task = fields.Boolean(related='job_id.add_test_task', string="Job has Test Task", readonly=True)

    def get_test_task_url(self):
        """ Generates the public link for the candidate (Public method) """
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return f"{base_url}/test-task/start?token={self.test_task_token}"

    def action_open_test_task(self):
        """ Button action to open the link in a new tab """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': self.get_test_task_url(),
            'target': 'new',
        }