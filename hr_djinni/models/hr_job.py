# Copyright © 2024 Garazd Creation (<https://garazd.biz>)
# @author: Yurii Razumovskyi (<support@garazd.biz>)
# @author: Iryna Razumovska (<support@garazd.biz>)
# License OPL-1 (https://www.odoo.com/documentation/15.0/legal/licenses.html).

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError, UserError


class HrJob(models.Model):
    _inherit = "hr.job"

    djinni_ref = fields.Char(string='Djinni ID', copy=False, readonly=True, tracking=True)
    djinni_account_id = fields.Many2one(comodel_name='djinni.account')
    djinni_domain_id = fields.Many2one(
        comodel_name='djinni.domain',
        string='Domain',
        readonly=True,
    )
    djinni_category_id = fields.Many2one(
        comodel_name='djinni.category',
        string='Category',
        readonly=True,
    )
    djinni_salary_deviation_id = fields.Many2one(
        comodel_name='djinni.salary.deviation',
        string='Acceptable Salary Deviation',
        readonly=True,
    )
    djinni_exp_years_deviation_id = fields.Many2one(
        comodel_name='djinni.exp.year.deviation',
        string='Acceptable Year Deviation',
        readonly=True,
    )
    djinni_eng_level_deviation_id = fields.Many2one(
        comodel_name='djinni.eng.level.deviation',
        string='Acceptable English Deviation',
        readonly=True,
    )
    djinni_country_id = fields.Many2one(
        comodel_name='djinni.country',
        string='Company Country',
        readonly=True,
    )
    djinni_region_id = fields.Many2one(
        string='Candidate Location',
        comodel_name='djinni.region',
        readonly=True,
    )
    djinni_city_id = fields.Many2one(
        comodel_name='djinni.city',
        string='Office City',
        readonly=True,
    )
    djinni_experience_id = fields.Many2one(
        comodel_name='djinni.experience',
        readonly=True,
    )
    djinni_english_level_id = fields.Many2one(
        comodel_name='djinni.eng.level',
        string='English Level',
        readonly=True,
    )
    djinni_company_type_id = fields.Many2one(
        comodel_name='djinni.company.type',
        string='Company Type',
        readonly=True,
    )
    djinni_remote_type_id = fields.Many2one(
        comodel_name='djinni.remote.type',
        string='Remote Type',
        readonly=True,
    )
    djinni_relocate_type_id = fields.Many2one(
        comodel_name='djinni.relocation',
        string='Relocation Type',
        readonly=True,
    )
    djinni_quiz_id = fields.Many2one(
        comodel_name='djinni.quiz',
        string='Quiz',
        readonly=True,
    )
    djinni_quiz_active_until = fields.Datetime(
        related='djinni_quiz_id.active_until',
        readonly=True,
    )
    djinni_quiz_question_ids = fields.One2many(
        related='djinni_quiz_id.question_ids',
        readonly=True,
    )
    djinni_public_salary_min = fields.Integer(
        string='Public Salary Min value',
        help='Minimal salary value which is displayed.',
        readonly=True,
    )
    djinni_public_salary_max = fields.Integer(
        string='Public Salary Max value',
        help='Maximum salary value which is displayed.',
        readonly=True,
    )
    djinni_salary_min = fields.Integer(string='Salary Min value', help='Minimal salary value.', readonly=True)
    djinni_salary_max = fields.Integer(string='Salary Max value', help='Maximum salary value.', readonly=True)
    djinni_singon_bonus = fields.Integer(string='Sign On Bonus', help='Bonus for accepting the offer', readonly=True)
    djinni_is_salary_public = fields.Boolean(string='Is Salary Public', readonly=True)
    djinni_is_part_time = fields.Boolean(string='Is Part-time job', readonly=True)
    djinni_has_test = fields.Boolean(string='Has Test Task', readonly=True)
    djinni_is_requires_cover_letter = fields.Boolean(string='Requires Cover Letter', readonly=True)
    djinni_is_ukraine_only = fields.Boolean(string='Only Ukraine', readonly=True)
    djinni_is_eng_level_strict = fields.Boolean(string='English Level is Strict', readonly=True)
    djinni_description = fields.Html(readonly=True)
    djinni_public_url = fields.Char()
    djinni_active = fields.Boolean(readonly=True)
    djinni_date = fields.Datetime(help='Created on Djinni', readonly=True)
    djinni_sync_date = fields.Datetime(string='Synced with Djinni', readonly=True)

    @api.constrains('djinni_ref', 'djinni_account_id', 'active')
    def _check_djinni_ref_unique(self):
        for rec in self:
            if self.search_count([
                    ('djinni_account_id', '!=', False),
                    ('djinni_account_id', '=', rec.djinni_account_id.id),
                    ('djinni_ref', '!=', False),
                    ('djinni_ref', '=', rec.djinni_ref),
                    ('active', '=', True),
            ]) > 1:
                raise ValidationError(_('The Djinni ID must be unique.'))

    def action_open_on_djinni(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': self.djinni_public_url,
            'target': 'new',
        }

    def action_set_djinni_ref(self):
        self.ensure_one()
        if self.djinni_ref:
            raise UserError(_("The Djinni ID is specified for this job. Choose another one."))
        return {
            'name': _('Setting a Djinni ID for the vacancy'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'djinni.set_ref',
            'context': {'default_job_id': self.id},
            'target': 'new',
        }

    def _djinni_prepare_job_vals(self):
        """ Generate values for the Djinni API requests. """
        self.ensure_one()
        job = self
        vals = {
            'position': job.name,
            'long_description': job.djinni_description,
            'recruiter': job.djinni_account_id.email,
            'domain': job.djinni_domain_id.ref,
            'acceptable_salary_deviation': job.djinni_salary_deviation_id.ref,
            'acceptable_exp_years_deviation': job.djinni_exp_years_deviation_id.ref,
            'acceptable_eng_level_deviation': job.djinni_eng_level_deviation_id.ref,
            'is_salary_public': job.djinni_is_salary_public,
            'external_data': {'external_job_id': str(job.id)},
            'accept_region': job.djinni_region_id.ref,
            'location': job.djinni_city_id.ref,
            'experience_years': float(job.djinni_experience_id.ref),
            'country': job.djinni_country_id.ref,
            'salary_min': job.djinni_salary_min,
            'salary_max': job.djinni_salary_max,
            'public_salary_min': job.djinni_public_salary_min,
            'public_salary_max': job.djinni_public_salary_max,
            'english_level': job.djinni_english_level_id.ref,
            'company_name': job.company_id.name,
            'is_parttime': job.djinni_is_part_time,
            'has_test': job.djinni_has_test,
            'requires_cover_letter': job.djinni_is_requires_cover_letter,
            'is_ukraine_only': job.djinni_is_ukraine_only,
            'company_type': job.djinni_company_type_id.ref,
            'remote_type': job.djinni_remote_type_id.ref,
            'relocate_type': job.djinni_relocate_type_id.ref,
            'signon_bonus': job.djinni_singon_bonus or 0,
            'primary_keyword': job.djinni_category_id.ref,
            'is_eng_level_strict': job.djinni_is_eng_level_strict,
        }
        # Remove keys with value False
        vals = {key: value for key, value in vals.items() if value is not False}
        return vals

    def action_create_update_djinni_vacancy(self):
        self.ensure_one()
        return {
            'name': _('Synchronization with Djinni'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'djinni.create_vacancy',
            'context': {'default_job_id': self.id},
            'target': 'new',
        }

    def djinni_create_vacancy(self):
        """ Request to create vacancy on Djinni """
        self.ensure_one()
        if self.djinni_ref:
            raise UserError(_('This job is already synced with Djinni.'))
        response = self.env['djinni.account']._djinni_api_request(
            account_ref=self.djinni_account_id.id,
            method='POST',
            params={'status': 'active' if self.djinni_active else 'inactive'},
            json=self._djinni_prepare_job_vals(),
            endpoint='/jobs/',
        )
        self.update({
            'djinni_ref': response['id'],
            'djinni_public_url': response['public_url'],
            'djinni_date':  self.convert_iso_date(response['created']),
            'djinni_sync_date': fields.Datetime.now(),
        })

    def djinni_update_vacancy(self, status: str = 'active'):
        """ Request to update vacancy on Djinni """
        self.ensure_one()
        if not self.djinni_ref:
            raise UserError(_('This job has not synced with Djinni.'))
        self.env['djinni.account']._djinni_api_request(
            account_ref=self.djinni_account_id.id,
            method='PUT',
            params={'status': status},
            json=self._djinni_prepare_job_vals(),
            endpoint=f'/jobs/{self.djinni_ref}',
        )
        self.update({'djinni_sync_date': fields.Datetime.now()})

    def djinni_delete_vacancy(self) -> None:
        self.ensure_one()
        if not self.djinni_ref:
            raise UserError(_('This job has not synced with Djinni.'))
        self.env['djinni.account']._djinni_api_request(
            account_ref=self.djinni_account_id.id,
            method='DELETE',
            endpoint=f'/jobs/{self.djinni_ref}',
            res_type='content',
        )
        self.update({'djinni_sync_date': fields.Datetime.now()})

    # flake8: noqa: E501
    def toggle_active(self):
        res = super(HrJob, self).toggle_active()
        for job in self.filtered(
                lambda jb: not jb.active and jb.djinni_ref and jb.djinni_account_id.company_id.djinni_deactivate_vacancy
        ):
            job.djinni_update_vacancy(status='inactive')
        return res

    def unlink(self):
        for job in self.filtered(
                lambda jb: jb.djinni_ref and jb.djinni_account_id.company_id.djinni_delete_vacancy
        ):
            job.djinni_delete_vacancy()
        return super(HrJob, self).unlink()
