# Copyright © 2024 Garazd Creation (https://garazd.biz)
# @author: Yurii Razumovskyi (support@garazd.biz)
# @author: Iryna Razumovska (support@garazd.biz)
# License OPL-1 (https://www.odoo.com/documentation/17.0/legal/licenses.html).

import logging
from typing import Dict, List

import requests
from requests.auth import HTTPBasicAuth

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.addons.garazd_request.utils.request import make_request

_logger = logging.getLogger(__name__)


class DjinniAccount(models.Model):
    _name = "djinni.account"
    _inherit = ['mail.thread']
    _description = 'Djinni Accounts'

    name = fields.Char(required=True)
    authorization_type = fields.Selection(selection=[('login', 'Login'), ('api_key', 'API Key')], required=True)
    email = fields.Char(help="The value will be used for the recruiter's email", required=True)
    secret = fields.Char(string='Password')
    api_key = fields.Char()
    job_count = fields.Integer(string='Vacancies', compute='_compute_job_count')
    debug_mode = fields.Boolean(help='Log debug messages to the Odoo log.')
    company_id = fields.Many2one(
        comodel_name='res.company',
        required=True,
        default=lambda self: self.env.user.company_id,
    )

    def _compute_job_count(self):
        for account in self:
            account.job_count = self.env['hr.job'].search_count([('djinni_account_id', '=', account.id)])

    def _djinni_api_request(
            self,
            account_ref: int,
            endpoint: str,
            method: str = 'GET',
            params: Dict = None,
            json: Dict = None,
            res_type='json',
    ):
        account = self.env['djinni.account'].browse(account_ref)
        headers = {}
        if account.authorization_type == 'api_key':
            headers.update({'X-API-Key': account.api_key})
        if json:
            headers.update({'Content-Type': 'application/json'})

        auth = None
        if account.authorization_type == 'login' and account.email and account.secret:
            auth = HTTPBasicAuth(account.email, account.secret)

        response_data: Dict = make_request(
            method=method,
            url=self.env['ir.config_parameter'].sudo().get_param('hr_djinni.djinni_api_url'),
            headers=headers,
            auth=auth,
            endpoint=endpoint,
            json=json,
            params=params,
            with_logs=account.debug_mode,
            api_name='Djinni API',
            res_type=res_type,
            # Client errors carry a body that explains WHICH field/value Djinni
            # rejected. The shared util hides it behind a bare "400 Bad Request",
            # so intercept these statuses and surface the real reason instead.
            http_status_to_skip=[400, 403, 409, 422],
        )
        if isinstance(response_data, requests.models.Response):
            self._raise_djinni_api_error(response_data)
        return response_data

    @api.model
    def _raise_djinni_api_error(self, response):
        """Raise a readable UserError from a Djinni client-error response.

        Djinni returns the validation details in the response body (JSON like
        ``{"field": ["message"]}`` or plain text). We unpack that so the user
        sees exactly what to fix instead of a generic "Invalid Operation".
        """
        details = ''
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            lines = []
            for field_name, messages in payload.items():
                if isinstance(messages, (list, tuple)):
                    messages = ', '.join(str(m) for m in messages)
                lines.append('• %s: %s' % (field_name, messages))
            details = '\n'.join(lines)
        elif isinstance(payload, list):
            details = '\n'.join('• %s' % item for item in payload)
        if not details:
            details = (response.text or '').strip()

        raise UserError(_(
            "Djinni rejected the request (HTTP %(code)s).\n\n"
            "%(details)s\n\n"
            "Tip: check that every required field of the vacancy is filled in "
            "before syncing. Enable \"Debug mode\" on the Djinni account to log "
            "the full request/response in the Odoo log.",
            code=response.status_code,
            details=details or _('No additional details were returned.'),
        ))

    def sync_api_list(self, model_name: str, endpoint: str) -> None:
        """ Get directory data. """
        self.ensure_one()

        # Get data by API
        api_list = self._djinni_api_request(account_ref=self.id, endpoint=f'/jobs/enums/{endpoint}')

        # Parse the response
        Model = self.env[f'djinni.{model_name}']
        directory_vals = []
        existing_refs = Model.search([]).mapped('ref')
        for element in api_list:
            vals = {
                'name': element['title'],
                'ref': element['value'],
            }
            if vals['ref'] not in existing_refs:
                directory_vals.append(vals)
        Model.sudo().create(directory_vals)

    @api.model
    def parse_quiz(self, quiz_list: List):
        HrJob = self.env['hr.job']
        DjinniQuiz = self.env['djinni.quiz']
        DjinniQuestion = self.env['djinni.quiz.question']
        for quiz in quiz_list:
            quiz_vals = {
                'name': quiz['name'],
                'ref': str(quiz['id']),
                'job_id': HrJob.search([('djinni_ref', '=', str(quiz['job_id']))], limit=1).id,
            }
            # Create or update the quiz
            quiz_id = DjinniQuiz.search([('ref', '=', quiz_vals['ref'])], limit=1)
            if quiz_id:
                quiz_id.write(quiz_vals)
            else:
                quiz_id = DjinniQuiz.create(quiz_vals)

            # Parse questions within the quiz
            for question in quiz['questions']:
                # flake8: noqa: E501
                question_vals = {
                    'name': question['text'],
                    'type_id': self.env['djinni.quiz.question.type'].search([('ref', '=', question['answer_type'])], limit=1).id,
                    'expected_answer': question['expected_answer'],
                    'sequence': question['visual_order'],
                    'quiz_id': quiz_id.id,
                }

                # Create or update the question
                question_id = DjinniQuestion.search([
                    ('quiz_id', '=', quiz_id.id),
                    ('name', '=', question['text']),
                ], limit=1)
                if question_id:
                    question_id.write(question_vals)
                else:
                    DjinniQuestion.create(question_vals)

    # flake8: noqa: E501
    def sync_job_list(self) -> None:
        """ Get jobs list. """
        for account in self:

            # Get jobs list by API
            job_list = account._djinni_api_request(
                account_ref=account.id,
                endpoint='/jobs/',
                params={'is_online': account.company_id.djinni_upload_active_vacancy}
            )

            # Parse the response
            HrJob = self.env['hr.job']
            job_vals = []
            quiz_list = []
            existing_jobs = HrJob.search([]).mapped('djinni_ref')
            for job in job_list['items']:
                vals = {
                    'djinni_account_id': account.id,
                    'djinni_ref': str(job['id']),
                    'name': job['position'],
                    'djinni_description': job['long_description'],
                    'djinni_public_url': job['public_url'],
                    'djinni_salary_min': job['salary_min'],
                    'djinni_salary_max': job['salary_max'],
                    'djinni_public_salary_min': job['public_salary_min'],
                    'djinni_public_salary_max': job['public_salary_max'],
                    'djinni_is_part_time': job['is_parttime'],
                    'djinni_has_test': job['has_test'],
                    'djinni_is_requires_cover_letter': job['requires_cover_letter'],
                    'djinni_is_ukraine_only': job['is_ukraine_only'],
                    'djinni_active': job['new_is_online'],
                    'djinni_singon_bonus': job['signon_bonus'],
                    'djinni_is_eng_level_strict': job['is_eng_level_strict'],
                    'djinni_date': self.env['hr.job'].convert_iso_date(job['published']),
                    'djinni_salary_deviation_id': self.env['djinni.salary.deviation'].search([('ref', '=', job['acceptable_salary_deviation'])],limit=1).id,
                    'djinni_exp_years_deviation_id': self.env['djinni.exp.year.deviation'].search([('ref', '=', job['acceptable_exp_years_deviation'])], limit=1).id,
                    'djinni_eng_level_deviation_id': self.env['djinni.eng.level.deviation'].search([('ref', '=', job['acceptable_eng_level_deviation'])], limit=1).id,
                    'djinni_country_id': self.env['djinni.country'].search([('ref', '=', job['country'])], limit=1).id,
                    'djinni_region_id': self.env['djinni.region'].search([('ref', '=', job['accept_region'])], limit=1).id,
                    'djinni_city_id':self.env['djinni.city'].search([('ref', '=', job['location'])], limit=1).id,
                    'djinni_experience_id': self.env['djinni.experience'].search([('ref', '=', job['exp_years'])], limit=1).id,
                    'djinni_domain_id': self.env['djinni.domain'].search([('ref', '=', job['domain'])],limit=1).id,
                    'djinni_english_level_id': self.env['djinni.eng.level'].search([('ref', '=', job['english_level'])], limit=1).id,
                    'djinni_company_type_id': self.env['djinni.company.type'].search([('ref', '=', job['company_type'])], limit=1).id,
                    'djinni_remote_type_id': self.env['djinni.remote.type'].search([('ref', '=', job['remote_type'])], limit=1).id,
                    'djinni_relocate_type_id': self.env['djinni.relocation'].search([('ref', '=', job['relocate_type'])], limit=1).id,
                    'djinni_category_id': self.env['djinni.category'].search([('ref', '=', job['primary_keyword'])], limit=1).id,
                    'djinni_sync_date': fields.Datetime.now(),
                }
                if job['quizzes']:
                    quiz_list.extend(job['quizzes'])
                if vals['djinni_ref'] not in existing_jobs:
                    job_vals.append(vals)
                else:
                    HrJob.search([('djinni_ref', '=', vals['djinni_ref'])], limit=1).sudo().write(vals)
            HrJob.sudo().create(job_vals)
            self.parse_quiz(quiz_list)

    def _get_applicant_vals(self, data, vals=None):
        """Method to add additional logic to process response."""
        return vals or {}

    def _process_applicant(self, applicant_vals):
        HrApplicant = self.env['hr.applicant']
        domain = [('djinni_ref', '=', applicant_vals.get('djinni_ref'))]
        hr_applicant = HrApplicant.with_context(active_test=False).search(domain, limit=1)

        # Update if the applicant exists
        if hr_applicant:
            hr_applicant.write(applicant_vals)
        else:
            applicant_vals.update({'stage_id': self.env.ref('hr_recruitment.stage_job0').id})
            hr_applicant = HrApplicant.create(applicant_vals)

        return hr_applicant

    def sync_applicant_list(self) -> None:
        """ Get job applicants list. """
        for account in self:
            existing_jobs = self.env['hr.job'].search([('djinni_ref', '!=', False)])
            for job in existing_jobs:
                # Get job applicants by API
                applicant_list = account._djinni_api_request(
                    account_ref=account.id,
                    endpoint=f'/jobs/{job.djinni_ref}/candidates',
                    params={'limit': 1000}
                )
                for applicant in applicant_list.get('items',[]):
                    description = []
                    if applicant.get('cover_letter'):
                        description.append('<h3>Cover letter:</h3><i>%s</i><hr/>' % applicant.get('cover_letter', ''))
                    if applicant.get('moreinfo'):
                        description.append('<h3>Experience:</h3>%s<hr/>' % applicant.get('moreinfo').replace('\n', '<br/>'))
                    if applicant.get('skills'):
                        description.append('<h3>Skills:</h3><ul>%s</ul><hr/>' % ''.join(
                            ['<li>%s</li>' % skill for skill in applicant.get('skills', [])]
                        ))
                    if applicant.get('highlights'):
                        description.append('<h3>Highlights:</h3>%s<hr/>' % applicant.get('highlights').replace('\n', '<br/>'))
                    if applicant.get('looking_for'):
                        description.append('<h3>Looking for:</h3>%s<hr/>' % applicant.get('looking_for').replace('\n', '<br/>'))
                    # Djinni often returns anonymous candidates with an empty
                    # name. `hr.applicant.name` (Subject / Application) is a
                    # required field in Odoo, so fall back to a stable, traceable
                    # label to keep the sync from failing. `partner_name` is not
                    # required, so it stays empty when the real name is unknown.
                    candidate_name = (applicant.get('name') or '').strip()
                    fallback_name = candidate_name or 'Djinni #%s — %s' % (
                        applicant['id'], job.name,
                    )
                    vals = {
                        'name': fallback_name,
                        'partner_name': candidate_name or False,
                        'djinni_ref': applicant['id'],
                        'djinni_date': self.env['hr.job'].convert_iso_date(applicant['applied_at']),
                        'djinni_candidate_url': applicant['public_profile_url'],
                        'djinni_candidate_cv_url': applicant.get('cv_url', ''),
                        'email_from': applicant.get('email', ''),
                        'partner_phone': applicant.get('phone', ''),
                        'linkedin_profile': applicant.get('linkedin', ''),
                        'salary_expected': applicant.get('salary_min', 0.0),
                        'description': '\n'.join(description),
                        'source_id': self.env.ref('hr_djinni.utm_source_djinni').id,
                        'job_id': job.id,
                    }

                    # Method to modify an applicant refs
                    applicant_vals = self._get_applicant_vals(applicant, vals)
                    applicant_id = self._process_applicant(applicant_vals)

                    # Download photo and set to image field
                    if applicant.get('picture_url') and not applicant_id.image_1920:
                        applicant_id.download_and_set_photo(applicant.get('picture_url'))

                    # Attach CV
                    if applicant.get('cv_url'):
                        applicant_id.download_and_link_attachment(applicant.get('cv_url'))

    @api.model
    def _get_api_base_objects(self) -> Dict:
        """ Return dictionary mapping database names (djinni.x) to API endpoints. """
        return {
            # 'recruiter': 'recruiters',
            'category': 'categories',
            'remote.type':'remote-types',
            'domain': 'domains',
            'country': 'countries',
            'city': 'cities',
            'relocation': 'relocations',
            'region': 'accept-regions',
            'experience': 'experiences',
            'eng.level': 'english-levels',
            'company.type': 'company-types',
            'salary.deviation': 'acceptable-salary-deviations',
            'exp.year.deviation': 'acceptable-exp-years-deviations',
            'eng.level.deviation': 'acceptable-eng-level-deviations',
            'quiz.question.type': 'answer-types',
        }

    @api.model
    def _synchronize_base(self):
        """ Sync base catalogs. """
        account = self.search(['|', ('api_key', '!=', False), ('secret', '!=', False)])[:1]
        if account:
            for key, ref in account._get_api_base_objects().items():
                account.sync_api_list(key, ref)

    @api.model
    def _get_sync_methods(self):
        return [
            'sync_job_list',
            'sync_applicant_list',
        ]

    @api.model
    def _synchronize(self, accounts=None) -> None:
        """ Sync account related data.
        :param accounts: recordset of 'djinni.account' model
        """
        if not accounts:
            accounts = self.search([])
        for method in self._get_sync_methods():
            getattr(accounts, method)()

    def action_sync(self):
        # Check if it's necessary to sync base catalogs
        if not self.env['djinni.category'].search_count([]):
            self._synchronize_base()
        self._synchronize(accounts=self)
