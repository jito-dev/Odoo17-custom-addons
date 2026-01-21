from odoo import models, fields, api
import statistics
import re
import unicodedata

def slugify(s):
    s = str(s)
    uni = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[\W_]+', '-', uni).strip('-').lower()
    return slug

class IqSurvey(models.Model):
    _name = 'iq.survey'
    _description = 'IQ Test Campaign'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    title = fields.Char('Campaign Title', required=True)
    description = fields.Html('Description')
    active = fields.Boolean('Active', default=True)
    
    slug = fields.Char('URL Slug', help="Unique identifier for public link", copy=False)
    
    access_mode = fields.Selection([
        ('email', 'Login by Email'),
        ('token', 'Token Only (Private/Recruitment)')
    ], string='Access Mode', default='token', required=True)
    
    test_url = fields.Char('Test Link', compute='_compute_test_url', readonly=True)
    job_id = fields.Many2one('hr.job', string="Related Job Position")
    question_ids = fields.Many2many('iq.question', string='Questions')
    user_input_ids = fields.One2many('iq.user_input', 'survey_id', string='Attempts')

    # Result Page Configuration (Simplified)
    result_msg_success = fields.Html('Success Message', translate=True, 
        default="<p>Thank You!<br/>Your test has been completed and your results have been saved successfully.<br/>We appreciate your participation.</p>")
    
    show_score = fields.Boolean('Show Score', default=True)
    show_category = fields.Boolean('Show Category', default=True)
    
    email_template_id = fields.Many2one('mail.template', string="Invitation Email Template",
        domain="[('model', '=', 'hr.applicant')]")

    # Statistics
    participant_count = fields.Integer("Participants", compute='_compute_statistics')
    min_score = fields.Integer("Min Score", compute='_compute_statistics')
    max_score = fields.Integer("Max Score", compute='_compute_statistics')
    average_score = fields.Float("Avg Score", compute='_compute_statistics', digits=(16, 2))
    median_score = fields.Float("Median Score", compute='_compute_statistics', digits=(16, 2))
    average_duration = fields.Float("Avg Time (min)", compute='_compute_statistics', digits=(16, 1))

    _sql_constraints = [('slug_unique', 'unique(slug)', 'The Slug must be unique!')]

    @api.depends('slug', 'access_mode')
    def _compute_test_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for rec in self:
            if rec.slug:
                rec.test_url = f"{base_url}/iq-test/go/{rec.slug}"
            else:
                rec.test_url = False

    @api.depends('user_input_ids.iq_score', 'user_input_ids.test_duration')
    def _compute_statistics(self):
        for survey in self:
            results = survey.user_input_ids.filtered(lambda r: r.iq_score > 0 or r.test_duration > 0)
            scores = results.mapped('iq_score')
            durations = results.mapped('test_duration')
            count = len(results)
            survey.participant_count = count
            if count > 0:
                survey.min_score = min(scores) if scores else 0
                survey.max_score = max(scores) if scores else 0
                survey.average_score = sum(scores) / count
                survey.median_score = statistics.median(scores) if scores else 0
                survey.average_duration = sum(durations) / count
            else:
                survey.min_score = 0
                survey.max_score = 0
                survey.average_score = 0.0
                survey.median_score = 0.0
                survey.average_duration = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        all_questions = self.env['iq.question'].search([])
        for vals in vals_list:
            if 'title' in vals and not vals.get('slug'):
                vals['slug'] = slugify(vals['title'])
            if not vals.get('question_ids'):
                vals['question_ids'] = [(6, 0, all_questions.ids)]
        return super().create(vals_list)

    def action_view_results(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Test Results',
            'res_model': 'iq.user_input',
            'view_mode': 'tree,form',
            'domain': [('survey_id', '=', self.id)],
            'context': {'default_survey_id': self.id}
        }
    
    def action_preview_result(self):
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return {
            'type': 'ir.actions.act_url',
            'url': f"{base_url}/iq-test/preview/{self.id}",
            'target': 'new',
        }