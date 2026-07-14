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
    sync_log_count = fields.Integer(string='Sync Logs', compute='_compute_sync_log_count')
    debug_mode = fields.Boolean(help='Log debug messages to the Odoo log.')
    company_id = fields.Many2one(
        comodel_name='res.company',
        required=True,
        default=lambda self: self.env.user.company_id,
    )

    def _compute_job_count(self):
        for account in self:
            account.job_count = self.env['hr.job'].search_count([('djinni_account_id', '=', account.id)])

    def _compute_sync_log_count(self):
        for account in self:
            account.sync_log_count = self.env['djinni.sync.log'].search_count([('account_id', '=', account.id)])

    def action_open_sync_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Djinni Sync Logs'),
            'res_model': 'djinni.sync.log',
            'view_mode': 'tree,form',
            'domain': [('account_id', '=', self.id)],
            'context': {'default_account_id': self.id},
        }

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
    def _djinni_job_payload_to_vals(self, job: Dict) -> Dict:
        """Map a Djinni vacancy payload to ``hr.job`` values.

        Shared by the (update-only) :meth:`sync_job_list` and the per-vacancy
        "Update Vacancy from Djinni" button so both write exactly the same fields.
        """
        self.ensure_one()
        return {
            'djinni_account_id': self.id,
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

    def list_djinni_vacancies(self) -> List[Dict]:
        """Return the account's vacancies from Djinni as raw payload dicts.

        Used by the manual "Link to Existing Djinni Vacancy" wizard to let the recruiter pick
        which exact vacancy to connect, instead of importing them all.
        """
        self.ensure_one()
        response = self._djinni_api_request(
            account_ref=self.id,
            endpoint='/jobs/',
            params={'is_online': self.company_id.djinni_upload_active_vacancy},
        )
        return response.get('items', []) if isinstance(response, dict) else []

    def sync_job_list(self, jobs=None):
        """Refresh the Djinni metadata of vacancies ALREADY linked in Odoo.

        This is deliberately *update-only*: it never creates an ``hr.job``.
        Vacancies are no longer auto-imported from Djinni — the recruiter
        creates the Odoo job and links it manually (see ``djinni.set_ref``),
        which prevents other recruiters' vacancies from being pulled into our
        recruitment pipeline. Here we only pull fresh metadata for vacancies
        that already carry a ``djinni_ref`` for this account.

        :param jobs: optional ``hr.job`` recordset to limit the refresh (the
            single-vacancy "Update Vacancy from Djinni" button). When omitted, every
            linked vacancy of the account is refreshed.
        :return: the ``hr.job`` recordset that was actually updated.
        """
        HrJob = self.env['hr.job']
        updated = HrJob
        for account in self:
            if jobs is not None:
                targets = jobs.filtered(
                    lambda j: j.djinni_account_id == account and j.djinni_ref
                )
            else:
                targets = HrJob.search([
                    ('djinni_account_id', '=', account.id),
                    ('djinni_ref', '!=', False),
                ])
            if not targets:
                continue
            targets_by_ref = {job.djinni_ref: job for job in targets}

            job_list = account._djinni_api_request(
                account_ref=account.id,
                endpoint='/jobs/',
                params={'is_online': account.company_id.djinni_upload_active_vacancy},
            )
            quiz_list = []
            for job in job_list['items']:
                target = targets_by_ref.get(str(job['id']))
                if not target:
                    # Vacancy exists on Djinni but is not linked in Odoo — never
                    # auto-create it; the recruiter links the ones they want.
                    continue
                target.sudo().write(account._djinni_job_payload_to_vals(job))
                updated |= target
                if job['quizzes']:
                    quiz_list.extend(job['quizzes'])
            if quiz_list:
                self.parse_quiz(quiz_list)
        return updated

    def _get_applicant_vals(self, data, vals=None):
        """Method to add additional logic to process response."""
        return vals or {}

    def _process_applicant(self, applicant_vals, job):
        """Create the applicant if new, otherwise leave the existing one untouched.

        The sync is deliberately *non-destructive*: once a candidate exists in
        Odoo we never write back over it, so recruiter edits (name, email,
        stage, contact, the vacancy they were moved to, …) are preserved across
        the every-30-min re-syncs. Existence is keyed on ``djinni_ref`` **and**
        ``job_id`` so the same person applying to two vacancies yields two
        independent applicant records instead of bouncing between jobs.

        :param job: the ``hr.job`` the candidate is imported into; its
            ``djinni_suppress_new_email`` flag decides whether the New-stage
            acknowledgement email is sent on import.
        :return: tuple ``(applicant, created)``. ``created`` is True only when a
            new record was inserted. An **empty** recordset with
            ``created=False`` signals an *ambiguous* email match (>1 candidate
            share the email) that the caller must skip and log.
        """
        HrApplicant = self.env['hr.applicant']
        existing = HrApplicant.with_context(active_test=False).search([
            ('djinni_ref', '=', applicant_vals.get('djinni_ref')),
            ('job_id', '=', applicant_vals.get('job_id')),
        ], limit=1)
        if existing:
            return existing, False

        # Secondary, email-based dedup. A candidate added through another channel
        # (manually, a tracking link, the website form, …) has no ``djinni_ref``,
        # so the ref lookup above misses it and a naive create would duplicate
        # the same person inside the same vacancy. Match such a record by email
        # (within this job, case-insensitive) and ADOPT it instead of twinning.
        email = (applicant_vals.get('email_from') or '').strip()
        if email:
            email_matches = HrApplicant.with_context(active_test=False).search([
                ('job_id', '=', applicant_vals.get('job_id')),
                ('email_from', '=ilike', email),
                '|', ('djinni_ref', '=', False), ('djinni_ref', '=', ''),
            ])
            if len(email_matches) > 1:
                # Ambiguous — refuse to guess which record is "the" candidate.
                # Create nothing; the caller counts it skipped and logs it.
                _logger.warning(
                    "Djinni: %d candidates in job %s (%s) share email %s and "
                    "have no Djinni id — skipping ref %s to avoid a wrong merge.",
                    len(email_matches), job.djinni_ref, job.name, email,
                    applicant_vals.get('djinni_ref'),
                )
                return HrApplicant, False
            if email_matches:
                # Exactly one: link it to Djinni without disturbing its pipeline.
                # Stamp ONLY the Djinni-owned, currently-empty fields (the ref,
                # and the profile blob). We deliberately do NOT touch `stage_id`,
                # `source_id` or any recruiter-owned field, and `applicant_origin`
                # ("Candidate Source") is NOT recomputed — it depends on
                # `tracker_id` only — so a manually/tracking-sourced candidate
                # keeps its original source. The caller then back-fills the
                # remaining empty contacts/photo/CV via enrichment.
                adopt_vals = {'djinni_ref': applicant_vals.get('djinni_ref')}
                if (applicant_vals.get('djinni_profile_html')
                        and not email_matches.djinni_profile_html):
                    adopt_vals['djinni_profile_html'] = applicant_vals['djinni_profile_html']
                email_matches.write(adopt_vals)
                email_matches.message_post(body=_(
                    "Linked to Djinni by email match (Djinni ID %s). Stage and "
                    "source kept; empty fields back-filled from the Djinni "
                    "profile. No acknowledgement email is sent.",
                    applicant_vals.get('djinni_ref')))
                return email_matches, False

        applicant_vals = dict(applicant_vals, stage_id=self.env.ref('hr_recruitment.stage_job0').id)
        # By default an imported candidate lands in the New stage and receives
        # the stock "Applicant: Acknowledgement" template (stage_job0.template_id),
        # fired by create-time field tracking (mail.thread.create ->
        # _message_track_post_template -> _track_template when `stage_id` is in
        # the created values). A recruiter can silence that per vacancy by
        # ticking ``djinni_suppress_new_email``: then we create with
        # `mail_notrack=True`, which skips ONLY that tracked-field template email
        # while keeping the chatter creation log and follower subscription. The
        # recruiter can still send it later by hand via the "Send Acknowledgement
        # Email" button, and manual stage moves keep firing their stage emails.
        HrApplicant = HrApplicant.with_context(mail_notrack=True) if job.djinni_suppress_new_email else HrApplicant
        return HrApplicant.create(applicant_vals), True

    # Page size for the paginated candidates endpoint. Djinni's private API has
    # no public spec, so confirm the param name (`offset`/`page`) on a live key.
    _CANDIDATES_PAGE_SIZE = 200
    # Hard safety cap so a misbehaving API (e.g. one that ignores `offset` and
    # keeps returning full pages) can never spin an infinite loop.
    _CANDIDATES_MAX = 50000

    def _iter_job_candidates(self, job):
        """Yield every candidate of a vacancy, paging until the list is exhausted.

        Previously the sync issued a single ``limit=1000`` request with no loop,
        so any vacancy with more than 1000 applicants silently lost the overflow.
        We page with ``limit``+``offset`` and stop only on an empty or
        all-duplicate page (the ``seen`` guard, which also makes the loop safe if
        the API ignores ``offset`` and keeps returning the first page) or at the
        hard ``_CANDIDATES_MAX`` cap.

        We deliberately do NOT stop on a *short* page: Djinni caps a page below
        the size we ask for (it returns ~100 even when we request 200), so the
        old ``len(items) < PAGE_SIZE: break`` halted after the first page and
        capped every import at ~100 candidates. For the same reason ``offset`` is
        advanced by the number of items the page *actually* returned, not by the
        size we requested — stepping by the requested size would skip every other
        window whenever the real page is smaller.
        """
        self.ensure_one()
        offset, seen = 0, set()
        while True:
            page = self._djinni_api_request(
                account_ref=self.id,
                endpoint=f'/jobs/{job.djinni_ref}/candidates',
                params={'limit': self._CANDIDATES_PAGE_SIZE, 'offset': offset},
            )
            items = page.get('items', []) if isinstance(page, dict) else []
            if not items:
                break
            fresh = [item for item in items if item.get('id') not in seen]
            if not fresh:
                # API ignored `offset` (same page again) — stop, don't loop.
                break
            seen.update(item.get('id') for item in items)
            for item in fresh:
                yield item
            offset += len(items)
            if offset >= self._CANDIDATES_MAX:
                _logger.warning(
                    "Djinni: pagination cap (%s) hit for job %s; some candidates "
                    "may be skipped.", self._CANDIDATES_MAX, job.djinni_ref,
                )
                break

    def _build_applicant_vals(self, applicant, job):
        """Map a Djinni candidate payload to ``hr.applicant`` values."""
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
        # Djinni often returns anonymous candidates with an empty name.
        # `hr.applicant.name` (Subject / Application) is required in Odoo, so fall
        # back to a stable, traceable label to keep the sync from failing.
        # `partner_name` is not required, so it stays empty when name is unknown.
        candidate_name = (applicant.get('name') or '').strip()
        fallback_name = candidate_name or 'Djinni #%s — %s' % (applicant['id'], job.name)
        # `applied_at` can be missing/empty; guard before parsing (was a hard
        # KeyError that aborted the whole vacancy).
        applied_at = applicant.get('applied_at')
        vals = {
            'name': fallback_name,
            'partner_name': candidate_name or False,
            # Store as text so it matches the Char field and the existence
            # search regardless of whether the API returns an int or a string.
            'djinni_ref': str(applicant['id']),
            'djinni_date': self.env['hr.job'].convert_iso_date(applied_at) if applied_at else False,
            'djinni_candidate_url': applicant.get('public_profile_url', ''),
            'djinni_candidate_cv_url': applicant.get('cv_url', ''),
            'email_from': applicant.get('email', ''),
            'partner_phone': applicant.get('phone', ''),
            'linkedin_profile': applicant.get('linkedin', ''),
            'salary_expected': applicant.get('salary_min', 0.0),
            # Write Djinni's profile blob to its own read-only field, NOT to the
            # native `description` — the sync runs every 30 min and would
            # otherwise overwrite any note the recruiter typed there.
            'djinni_profile_html': '\n'.join(description),
            'source_id': self.env.ref('hr_djinni.utm_source_djinni').id,
            'job_id': job.id,
        }
        return self._get_applicant_vals(applicant, vals)

    def _sync_job_candidates(self, job):
        """Pull and create the new candidates of a single vacancy.

        The pull is idempotent: candidates already in Odoo are never created
        twice and their recruiter-owned fields are never overwritten (see
        :meth:`_process_applicant`). The one exception is *back-filling*: when a
        previously anonymous candidate opens their contacts on Djinni, the empty
        contact fields are filled in (see
        :meth:`hr.applicant._djinni_enrich_from_sync`) and the candidate is
        counted as ``updated``; otherwise it is ``skipped``.

        :return: dict with ``new``/``updated``/``skipped`` counters.
        """
        self.ensure_one()
        stats = {'new': 0, 'updated': 0, 'skipped': 0, 'notes': []}
        for applicant in self._iter_job_candidates(job):
            if not applicant.get('id'):
                stats['skipped'] += 1
                continue
            # Skip anonymous candidates: Djinni lists people before they reveal
            # their contacts, and recruiters don't want those imported as
            # placeholder "Djinni #<ref>" cards. We don't create them at all —
            # the candidate is keyed on the stable `djinni_ref`, so once they
            # reveal a name/email a later sync imports them exactly once, fully
            # formed (no duplicate). "Anonymous" mirrors the module's own
            # contacts-revealed definition — no name AND no email — see
            # `hr.applicant._djinni_enrich_from_sync`.
            if not (applicant.get('name') or '').strip() \
                    and not (applicant.get('email') or '').strip():
                stats['skipped'] += 1
                continue
            applicant_vals = self._build_applicant_vals(applicant, job)
            applicant_id, created = self._process_applicant(applicant_vals, job)
            if not applicant_id:
                # Ambiguous email match (>1 candidate share the email, all
                # without a Djinni id): skipped to avoid a wrong merge. Surface
                # it in the sync log so a recruiter can resolve the duplicates.
                stats['skipped'] += 1
                stats['notes'].append(
                    'Ambiguous email match in %s (%s): %s on several candidates '
                    '— Djinni ref %s skipped.' % (
                        job.djinni_ref, job.name,
                        applicant_vals.get('email_from'),
                        applicant_vals.get('djinni_ref')))
                continue
            if not created:
                # Already in Odoo: never overwrite it, but back-fill the contact
                # fields that are still empty if Djinni has since revealed them.
                if applicant_id._djinni_enrich_from_sync(applicant_vals, applicant):
                    stats['updated'] += 1
                else:
                    stats['skipped'] += 1
                continue
            stats['new'] += 1

            if applicant.get('picture_url'):
                applicant_id.download_and_set_photo(applicant.get('picture_url'))
            # Attach CV (the helper dedupes by URL).
            if applicant.get('cv_url'):
                applicant_id.download_and_link_attachment(applicant.get('cv_url'))

        job.sudo().write({'djinni_last_applicant_sync': fields.Datetime.now()})
        return stats

    def sync_applicant_list(self, enforce_interval=True, trigger='cron') -> None:
        """Pull candidates for the vacancies that opted in to auto-sync.

        Only vacancies with ``djinni_auto_sync_candidates`` enabled are pulled,
        so the (paid) data extraction never runs for vacancies the recruiter did
        not choose. When ``enforce_interval`` is True (the cron tick) a vacancy is
        skipped until its ``djinni_sync_interval`` has elapsed; the account-wide
        manual "Synchronization" button passes False to force a pull now.

        Each vacancy is isolated in its own savepoint so a failure on one does
        not abort the whole batch, and the run is recorded in ``djinni.sync.log``.
        """
        now = fields.Datetime.now()
        for account in self:
            jobs = account._candidate_jobs_to_sync(enforce_interval, now)
            if jobs:
                account._run_applicant_sync(jobs=jobs, trigger=trigger)

    def _enqueue_applicant_sync(self, enforce_interval=True, trigger='cron'):
        """Cron entrypoint: queue one background candidate pull per account.

        The cron tick must return immediately, so the heavy (and potentially
        paid) Djinni candidate pull is delegated to a ``queue_job`` worker
        instead of running inline. One job is queued per account on the
        dedicated ``root.djinni`` channel; the ``identity_key`` collapses
        duplicate enqueues so a tick firing while the previous job is still
        pending cannot double-pull and burn credits.

        The opt-in + interval gates are deliberately NOT evaluated here: the
        worker re-resolves the due vacancies with a fresh ``now`` (see
        :meth:`_job_account_applicant_sync`), so a job that waited in the queue
        still pulls exactly what is due at execution time — keeping the paid
        request count identical to the old inline cron.

        Only the cron uses this method. The manual buttons keep calling the
        synchronous :meth:`sync_applicant_list` / :meth:`_run_applicant_sync`
        so their toast can report real counts.
        """
        for account in self:
            account.with_delay(
                channel='root.djinni',
                identity_key='djinni_applicant_sync_%s' % account.id,
                description='Djinni applicant sync: %s' % (account.display_name or account.id),
                max_retries=3,
            )._job_account_applicant_sync(enforce_interval=enforce_interval, trigger=trigger)

    def _job_account_applicant_sync(self, enforce_interval=True, trigger='cron'):
        """``queue_job`` worker performing the candidate pull for one account.

        Delegates to the synchronous :meth:`sync_applicant_list`, which
        re-resolves the due, opted-in vacancies at execution time.
        """
        self.ensure_one()
        self.sync_applicant_list(enforce_interval=enforce_interval, trigger=trigger)

    def _candidate_jobs_to_sync(self, enforce_interval, now):
        """Return the auto-sync-enabled vacancies of this account that are due."""
        self.ensure_one()
        jobs = self.env['hr.job'].search([
            ('djinni_ref', '!=', False),
            ('djinni_account_id', '=', self.id),
            ('djinni_auto_sync_candidates', '=', True),
        ])
        if enforce_interval:
            jobs = jobs.filtered(lambda job: job._djinni_candidate_sync_due(now))
        return jobs

    def _run_applicant_sync(self, jobs=None, trigger='cron'):
        """Core sync loop shared by the cron and the manual per-vacancy button.

        :param jobs: optional ``hr.job`` recordset to limit the sync (manual run).
        :return: the created ``djinni.sync.log`` record.
        """
        self.ensure_one()
        if jobs is None:
            jobs = self.env['hr.job'].search([('djinni_ref', '!=', False)])
        start = fields.Datetime.now()
        totals = {'new': 0, 'updated': 0, 'skipped': 0, 'errors': 0}
        notes = []
        for job in jobs:
            try:
                with self.env.cr.savepoint():
                    stats = self._sync_job_candidates(job)
                totals['new'] += stats['new']
                totals['updated'] += stats['updated']
                totals['skipped'] += stats['skipped']
                notes.extend(stats.get('notes', []))
            except Exception as error:
                totals['errors'] += 1
                notes.append('[%s] %s: %s' % (job.djinni_ref, job.name, error))
                _logger.exception(
                    "Djinni: applicant sync failed for job %s (%s)",
                    job.djinni_ref, job.name,
                )

        if totals['errors'] and (totals['new'] or totals['updated']):
            state = 'partial'
        elif totals['errors']:
            state = 'error'
        else:
            state = 'success'
        return self.env['djinni.sync.log'].sudo().create({
            'account_id': self.id,
            'date_start': start,
            'date_end': fields.Datetime.now(),
            'state': state,
            'trigger': trigger,
            'job_count': len(jobs),
            'new_count': totals['new'],
            'updated_count': totals['updated'],
            'skipped_count': totals['skipped'],
            'error_count': totals['errors'],
            'note': '\n'.join(notes) or False,
        })

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
        # The cron NO LONGER touches vacancies: they are never auto-created and
        # their metadata is refreshed only on demand (the per-vacancy "Pull from
        # Djinni" button or the account-level manual sync). The tick only
        # delegates the heavy candidate pull to queue_job via
        # ``_enqueue_applicant_sync`` so it returns immediately.
        return [
            '_enqueue_applicant_sync',
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
        # Refresh the metadata of the already-linked vacancies (update-only —
        # never imports new ones), then pull candidates for the auto-sync
        # vacancies right now (manual button bypasses the interval throttle, but
        # still respects each vacancy's auto-sync opt-in to avoid surprise spend).
        self.sync_job_list()
        self.sync_applicant_list(enforce_interval=False, trigger='manual')
