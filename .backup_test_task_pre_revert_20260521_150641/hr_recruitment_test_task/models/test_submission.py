from odoo import models, fields

class TestTaskSubmission(models.Model):
    _name = 'hr.test.submission'
    _description = 'Test Task Submission'
    _order = 'create_date desc'

    applicant_id = fields.Many2one('hr.applicant', string="Applicant", required=True, ondelete='cascade')
    github_link = fields.Char("GitHub Repository", required=True)
    additional_info = fields.Text("Additional Info")
    version = fields.Integer("Submission Version", default=1)