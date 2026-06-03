# Copyright © 2024 Garazd Creation (https://garazd.biz)
# @author: Yurii Razumovskyi (support@garazd.biz)
# @author: Iryna Razumovska (support@garazd.biz)
# License OPL-1 (https://www.odoo.com/documentation/17.0/legal/licenses.html).

from odoo import api, fields, models


class DjinniCreateVacancy(models.TransientModel):
    _name = "djinni.create_vacancy"
    _description = 'Wizard to modify a Djinni vacancy'

    job_id = fields.Many2one(
        comodel_name='hr.job',
        string='Vacancy',
        required=True,
    )
    djinni_ref = fields.Char(string='Djinni ID', related='job_id.djinni_ref')
    account_id = fields.Many2one(
        comodel_name='djinni.account',
        required=True,
    )
    active = fields.Boolean()
    description = fields.Html()
    domain_id = fields.Many2one(comodel_name='djinni.domain')
    category_id = fields.Many2one(comodel_name='djinni.category')
    salary_deviation_id = fields.Many2one(
        comodel_name='djinni.salary.deviation',
        string='Acceptable Salary Deviation',
    )
    exp_years_deviation_id = fields.Many2one(
        comodel_name='djinni.exp.year.deviation',
        string='Acceptable Year Deviation',
    )
    eng_level_deviation_id = fields.Many2one(
        comodel_name='djinni.eng.level.deviation',
        string='Acceptable English Deviation',
    )
    region_id = fields.Many2one(string='Candidate Location', comodel_name='djinni.region')
    city_id = fields.Many2one(string='Office City', comodel_name='djinni.city')
    country_id = fields.Many2one(string='Company Country', comodel_name='djinni.country')
    experience_id = fields.Many2one(comodel_name='djinni.experience')
    english_level_id = fields.Many2one(comodel_name='djinni.eng.level')
    company_type_id = fields.Many2one(comodel_name='djinni.company.type')
    quiz_id = fields.Many2one(comodel_name='djinni.quiz')
    quiz_ref = fields.Char(related='quiz_id.ref', string='Ref')
    quiz_question_ids = fields.Many2many(comodel_name='djinni.quiz.question')
    remote_type_id = fields.Many2one(comodel_name='djinni.remote.type')
    relocate_type_id = fields.Many2one(comodel_name='djinni.relocation')
    public_salary_min = fields.Integer(string='Public Salary Min Value')
    public_salary_max = fields.Integer(string='Public Salary Max Value')
    salary_min = fields.Integer(string='Salary Min Value', help='Minimal salary value.')
    salary_max = fields.Integer(string='Salary Max Value', help='Maximum salary value.')
    singon_bonus = fields.Integer(string='Sign On Bonus', help='Bonus for accepting the offer')
    is_salary_public = fields.Boolean()
    is_part_time = fields.Boolean(string='Is Part-time job')
    has_test = fields.Boolean(string='Has Test Task')
    is_requires_cover_letter = fields.Boolean(string='Requires Cover Letter')
    is_ukraine_only = fields.Boolean(string='Only Ukraine')
    is_eng_level_strict = fields.Boolean(string='English Level is Strict')

    @api.model
    def default_get(self, fields_list):
        vals = super(DjinniCreateVacancy, self).default_get(fields_list)
        if vals.get('job_id'):
            vals.update(self._get_job_vals(self.env['hr.job'].browse(vals.get('job_id'))))
        else:
            if not vals.get('country_id'):
                vals['country_id'] = self.env['djinni.country'].search([('ref', '=', 'UKR')], limit=1).id
        if not vals.get('account_id'):
            vals['account_id'] = self.env['djinni.account'].search([], limit=1).id
        return vals

    @api.model
    def _get_job_vals(self, job):
        vals = {
            'account_id': self.env['djinni.account'].search([], limit=1).id,
            'description': job.djinni_description,
            'domain_id': job.djinni_domain_id.id,
            'active': job.djinni_active,
            'category_id': job.djinni_category_id.id,
            'salary_deviation_id': job.djinni_salary_deviation_id.id,
            'exp_years_deviation_id': job.djinni_exp_years_deviation_id.id,
            'eng_level_deviation_id': job.djinni_eng_level_deviation_id.id,
            'country_id': job.djinni_country_id.id,
            'region_id': job.djinni_region_id.id,
            'city_id': job.djinni_city_id.id,
            'experience_id': job.djinni_experience_id.id,
            'english_level_id': job.djinni_english_level_id.id,
            'company_type_id': job.djinni_company_type_id.id,
            'remote_type_id': job.djinni_remote_type_id.id,
            'relocate_type_id': job.djinni_relocate_type_id.id,
            'quiz_id': job.djinni_quiz_id.id,
            'quiz_question_ids': job.djinni_quiz_id.question_ids,
            'public_salary_min': job.djinni_public_salary_min,
            'public_salary_max': job.djinni_public_salary_max,
            'salary_min': job.djinni_salary_min,
            'salary_max': job.djinni_salary_max,
            'singon_bonus': job.djinni_singon_bonus,
            'is_salary_public': job.djinni_is_salary_public,
            'is_part_time': job.djinni_is_part_time,
            'has_test': job.djinni_has_test,
            'is_requires_cover_letter': job.djinni_is_requires_cover_letter,
            'is_ukraine_only': job.djinni_is_ukraine_only,
            'is_eng_level_strict': job.djinni_is_eng_level_strict,
        }
        return vals

    def _prepare_job_vals(self):
        self.ensure_one()
        return {
            'djinni_account_id': self.account_id.id,
            'djinni_description': self.description,
            'djinni_domain_id': self.domain_id.id,
            'djinni_active': self.active,
            'djinni_category_id': self.category_id.id,
            'djinni_salary_deviation_id': self.salary_deviation_id.id,
            'djinni_exp_years_deviation_id': self.exp_years_deviation_id.id,
            'djinni_eng_level_deviation_id': self.eng_level_deviation_id.id,
            'djinni_country_id': self.country_id.id,
            'djinni_region_id': self.region_id.id,
            'djinni_city_id': self.city_id.id,
            'djinni_experience_id': self.experience_id.id,
            'djinni_english_level_id': self.english_level_id.id,
            'djinni_company_type_id': self.company_type_id.id,
            'djinni_remote_type_id': self.remote_type_id.id,
            'djinni_relocate_type_id': self.relocate_type_id.id,
            'djinni_is_salary_public': self.is_salary_public,
            'djinni_public_salary_min': self.public_salary_min if self.is_salary_public else 0,
            'djinni_public_salary_max': self.public_salary_max if self.is_salary_public else 0,
            'djinni_salary_min': self.salary_min,
            'djinni_salary_max': self.salary_max,
            'djinni_is_part_time': self.is_part_time,
            'djinni_has_test': self.has_test,
            'djinni_is_requires_cover_letter': self.is_requires_cover_letter,
            'djinni_is_ukraine_only': self.is_ukraine_only,
            'djinni_singon_bonus': self.singon_bonus or 0,
            'djinni_is_eng_level_strict': self.is_eng_level_strict,
        }

    def _prepare_quiz_vals(self):
        self.ensure_one()
        return {
            'name': self.quiz_id.name,
            'job_id': self.job_id.id,
            'active_until': self.quiz_id.active_until,
            'question_ids': [(6, 0, self.quiz_question_ids.ids)],
        }

    def action_create(self):
        """ Create a vacancy and quiz on the Djinni side. """
        self.ensure_one()
        # Request to create vacancy
        self.job_id.write(self._prepare_job_vals())
        self.job_id.djinni_create_vacancy()
        # Requests to create quiz and questions (only when a quiz is selected;
        # the quiz models call ensure_one() and would crash on an empty record).
        if self.quiz_id:
            self.quiz_id.write(self._prepare_quiz_vals())
            self.quiz_id.create_quiz()
            self.quiz_id.create_questions()

    def action_sync(self):
        """ Update a vacancy and quiz data from Odoo to Djinni. """
        self.ensure_one()
        # Request to update vacancy
        self.job_id.write(self._prepare_job_vals())
        self.job_id.djinni_update_vacancy()
        # Requests to update quiz and questions (only when a quiz is selected;
        # the quiz models call ensure_one() and would crash on an empty record).
        if self.quiz_id:
            self.quiz_id.write(self._prepare_quiz_vals())
            self.quiz_id.update_quiz()
            self.quiz_id.update_questions()
