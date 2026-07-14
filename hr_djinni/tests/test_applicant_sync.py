# Copyright © 2024 Garazd Creation (https://garazd.biz)
# License OPL-1 (https://www.odoo.com/documentation/17.0/legal/licenses.html).

from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

CANDIDATES = 'odoo.addons.hr_djinni.models.djinni_account.DjinniAccount._djinni_api_request'


def _make_candidates(prefix, total):
    """Build a list of fake Djinni candidate payloads."""
    return [{
        'id': '%s-%s' % (prefix, i),
        'name': 'Candidate %s %s' % (prefix, i),
        'applied_at': '2024-01-01T00:00:00',
        'public_profile_url': 'https://djinni.co/q/%s-%s' % (prefix, i),
    } for i in range(total)]


@tagged('post_install', '-at_install')
class TestApplicantSync(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.account = cls.env['djinni.account'].create({
            'name': 'Test Djinni',
            'authorization_type': 'api_key',
            'email': 'magic@example.com',
            'api_key': 'x',
        })
        cls.job_a = cls.env['hr.job'].create({'name': 'Python Dev', 'djinni_ref': '111'})
        cls.job_b = cls.env['hr.job'].create({'name': 'QA Engineer', 'djinni_ref': '222'})

    def _count(self, prefix):
        return self.env['hr.applicant'].with_context(active_test=False).search_count(
            [('djinni_ref', 'like', '%s-' % prefix)]
        )

    def test_pagination_pulls_beyond_one_page(self):
        """All candidates are imported even when they span several API pages."""
        # 450 > page size (200) -> proves the loop, not a single capped request.
        data = _make_candidates('A', 450)

        def fake(self, account_ref, endpoint, method='GET', params=None,
                 json=None, res_type='json'):
            offset = (params or {}).get('offset', 0)
            limit = (params or {}).get('limit', 200)
            return {'items': data[offset:offset + limit]}

        with patch(CANDIDATES, new=fake):
            log = self.account._run_applicant_sync(jobs=self.job_a, trigger='manual')

        self.assertEqual(self._count('A'), 450, 'every paged candidate must be imported')
        self.assertEqual(log.new_count, 450)
        self.assertEqual(log.state, 'success')
        self.assertTrue(self.job_a.djinni_last_applicant_sync)

    def test_pagination_survives_api_capped_page_size(self):
        """Djinni caps a page below the size we ask for (returns ~100 even when
        we request 200). The loop must page on past that short page instead of
        stopping at it — the old `len(items) < PAGE_SIZE: break` capped the whole
        import at one page (~100)."""
        data = _make_candidates('A', 250)
        api_cap = 100  # the API never returns more than this per page

        def fake(self, account_ref, endpoint, method='GET', params=None,
                 json=None, res_type='json'):
            offset = (params or {}).get('offset', 0)
            limit = min((params or {}).get('limit', 200), api_cap)
            return {'items': data[offset:offset + limit]}

        with patch(CANDIDATES, new=fake):
            log = self.account._run_applicant_sync(jobs=self.job_a, trigger='manual')

        self.assertEqual(self._count('A'), 250,
                         'every candidate must import even when the API caps the page at 100')
        self.assertEqual(log.new_count, 250)

    def _make_legacy_anonymous(self, job, ref):
        """Create a candidate the way the pre-v17.0.8.0.0 sync imported anonymous
        ones (placeholder subject, no contacts). The sync no longer creates these
        — anonymous candidates are skipped on import — but cards already in Odoo
        (and any still missing contacts) must still be enriched in place once
        Djinni reveals the real data, which is what these tests pin down."""
        return self.env['hr.applicant'].create({
            'name': 'Djinni #%s — %s' % (ref, job.name),
            'djinni_ref': ref,
            'job_id': job.id,
        })

    def test_enrichment_backfills_contacts_once_revealed(self):
        """An already-imported candidate still missing contacts gets its empty
        contact fields filled in (and is counted as updated) once Djinni reveals
        the real data — in place, with no duplicate."""
        rec = self._make_legacy_anonymous(self.job_a, 'DJ-1')
        self.assertTrue(rec.name.startswith('Djinni #DJ-1'),
                        'precondition: the legacy card uses the placeholder subject')
        self.assertFalse(rec.partner_name)
        self.assertFalse(rec.djinni_contacts_revealed)

        def fake(self, account_ref, endpoint, method='GET', params=None,
                 json=None, res_type='json'):
            offset = (params or {}).get('offset', 0)
            if offset:
                return {'items': []}
            # Candidate has opened their contacts -> Djinni now returns them.
            return {'items': [{
                'id': 'DJ-1', 'name': 'Real Person',
                'email': 'real@example.com', 'phone': '+380501112233',
                'applied_at': '2024-01-01T00:00:00',
                'public_profile_url': 'https://djinni.co/q/DJ-1',
            }]}

        with patch(CANDIDATES, new=fake):
            log = self.account._run_applicant_sync(jobs=self.job_a, trigger='manual')

        self.assertEqual(self._count('DJ'), 1, 'no duplicate on the enriching sync')
        self.assertEqual(rec.partner_name, 'Real Person')
        self.assertEqual(rec.name, 'Real Person', 'placeholder subject swapped for the real name')
        self.assertEqual(rec.email_from, 'real@example.com')
        self.assertEqual(rec.partner_phone, '+380501112233')
        self.assertTrue(rec.djinni_contacts_revealed)
        self.assertEqual(log.updated_count, 1, 'a back-filled candidate counts as updated')
        self.assertEqual(log.new_count, 0)
        # The enrichment must leave a chatter note naming the filled fields,
        # since these contact fields are not Odoo-tracked.
        note = rec.message_ids.filtered(lambda m: 'back-filled' in (m.body or ''))
        self.assertTrue(note, 'enrichment must post a chatter note listing filled fields')
        self.assertIn('Email', note[0].body)
        self.assertIn('Phone', note[0].body)

    def test_enrichment_never_overwrites_recruiter_edits_or_stage(self):
        """Back-fill fills only EMPTY fields: a recruiter-renamed subject and a
        manual stage move must survive the enriching sync untouched."""
        rec = self._make_legacy_anonymous(self.job_a, 'DJ-2')
        interview = self.env.ref('hr_recruitment.stage_job1')
        # Recruiter renames the card and moves it forward on the kanban.
        rec.write({'name': 'My Own Label', 'stage_id': interview.id})

        def fake(self, account_ref, endpoint, method='GET', params=None,
                 json=None, res_type='json'):
            offset = (params or {}).get('offset', 0)
            if offset:
                return {'items': []}
            return {'items': [{
                'id': 'DJ-2', 'name': 'Real Person',
                'email': 'real@example.com',
                'applied_at': '2024-01-01T00:00:00',
                'public_profile_url': 'https://djinni.co/q/DJ-2',
            }]}

        with patch(CANDIDATES, new=fake):
            self.account._run_applicant_sync(jobs=self.job_a, trigger='manual')

        self.assertEqual(rec.name, 'My Own Label',
                         'a recruiter-edited subject must never be overwritten')
        self.assertEqual(rec.stage_id, interview,
                         'enrichment must never touch the stage')
        # Empty contact fields are still back-filled (they were never edited).
        self.assertEqual(rec.partner_name, 'Real Person')
        self.assertEqual(rec.email_from, 'real@example.com')

    def test_anonymous_candidates_are_skipped_on_import(self):
        """A candidate Djinni lists before they reveal contacts (no name AND no
        email) is NOT imported — no placeholder card is created. Once they reveal
        a name/email a later sync imports them exactly once, fully formed."""
        state = {'revealed': False}

        def fake(self, account_ref, endpoint, method='GET', params=None,
                 json=None, res_type='json'):
            offset = (params or {}).get('offset', 0)
            if offset:
                return {'items': []}
            if state['revealed']:
                return {'items': [{
                    'id': 'ANON-1', 'name': 'Now Visible',
                    'email': 'now@example.com',
                    'applied_at': '2024-01-01T00:00:00',
                    'public_profile_url': 'https://djinni.co/q/ANON-1',
                }]}
            # Anonymous: Djinni hides both the name and the contacts.
            return {'items': [{
                'id': 'ANON-1', 'applied_at': '2024-01-01T00:00:00',
                'public_profile_url': 'https://djinni.co/q/ANON-1',
            }]}

        with patch(CANDIDATES, new=fake):
            log1 = self.account._run_applicant_sync(jobs=self.job_a, trigger='manual')
            self.assertFalse(
                self.env['hr.applicant'].with_context(active_test=False).search(
                    [('djinni_ref', '=', 'ANON-1')]),
                'an anonymous candidate must not be imported at all')
            self.assertEqual(log1.new_count, 0)
            self.assertEqual(log1.skipped_count, 1,
                             'the anonymous candidate is counted as skipped')

            # Candidate opens their contacts -> the next sync imports them once.
            state['revealed'] = True
            log2 = self.account._run_applicant_sync(jobs=self.job_a, trigger='manual')

        recs = self.env['hr.applicant'].with_context(active_test=False).search(
            [('djinni_ref', '=', 'ANON-1')])
        self.assertEqual(len(recs), 1,
                         'revealed candidate imported exactly once, no duplicate')
        self.assertEqual(recs.partner_name, 'Now Visible')
        self.assertEqual(recs.email_from, 'now@example.com')
        self.assertEqual(log2.new_count, 1)

    def test_one_failing_vacancy_does_not_abort_the_batch(self):
        """A failure on one vacancy is isolated; the others still sync."""
        data_a = _make_candidates('A', 5)

        def fake(self, account_ref, endpoint, method='GET', params=None,
                 json=None, res_type='json'):
            if '/jobs/222/' in endpoint:
                raise ValueError('boom from Djinni')
            offset = (params or {}).get('offset', 0)
            limit = (params or {}).get('limit', 200)
            return {'items': data_a[offset:offset + limit]}

        with patch(CANDIDATES, new=fake):
            log = self.account._run_applicant_sync(
                jobs=self.job_a | self.job_b, trigger='cron')

        self.assertEqual(self._count('A'), 5, 'healthy vacancy must still import')
        self.assertEqual(log.error_count, 1)
        self.assertEqual(log.state, 'partial')
        self.assertIn('222', log.note or '')

    def test_profile_goes_to_djinni_field_not_description(self):
        """Djinni profile blob lands in djinni_profile_html, never in description."""
        candidate = {
            'id': 'A-1', 'name': 'Jane', 'applied_at': '2024-01-01T00:00:00',
            'public_profile_url': 'https://djinni.co/q/A-1',
            'cover_letter': 'Hire me', 'skills': ['Python', 'Odoo'],
        }

        def fake(self, account_ref, endpoint, method='GET', params=None,
                 json=None, res_type='json'):
            offset = (params or {}).get('offset', 0)
            return {'items': [candidate] if offset == 0 else []}

        with patch(CANDIDATES, new=fake):
            self.account._run_applicant_sync(jobs=self.job_a, trigger='manual')

        rec = self.env['hr.applicant'].search([('djinni_ref', '=', 'A-1')])
        self.assertTrue(rec.djinni_profile_html, 'profile must populate djinni_profile_html')
        self.assertIn('Python', rec.djinni_profile_html)
        self.assertFalse(rec.description, 'sync must not write the native description')

    def test_resync_preserves_recruiter_description(self):
        """A recruiter note in description survives a re-sync of the same candidate."""
        candidate = {
            'id': 'A-1', 'name': 'Jane', 'applied_at': '2024-01-01T00:00:00',
            'public_profile_url': 'https://djinni.co/q/A-1', 'skills': ['Python'],
        }

        def fake(self, account_ref, endpoint, method='GET', params=None,
                 json=None, res_type='json'):
            offset = (params or {}).get('offset', 0)
            return {'items': [candidate] if offset == 0 else []}

        with patch(CANDIDATES, new=fake):
            self.account._run_applicant_sync(jobs=self.job_a, trigger='manual')
            rec = self.env['hr.applicant'].search([('djinni_ref', '=', 'A-1')])
            rec.description = '<p>Recruiter note: strong candidate</p>'
            # second sync (same candidate) -> skip path, record left untouched
            self.account._run_applicant_sync(jobs=self.job_a, trigger='manual')

        self.assertIn('Recruiter note', rec.description,
                      'sync must never overwrite the recruiter-owned description')

    def test_resync_is_idempotent_and_non_destructive(self):
        """A re-sync of a known candidate creates no duplicate and overwrites
        nothing — recruiter edits to Djinni-sourced fields survive."""
        candidate = {
            'id': 'A-1', 'name': 'Original Name', 'applied_at': '2024-01-01T00:00:00',
            'public_profile_url': 'https://djinni.co/q/A-1',
            'email': 'from-djinni@example.com',
        }

        def fake(self, account_ref, endpoint, method='GET', params=None,
                 json=None, res_type='json'):
            offset = (params or {}).get('offset', 0)
            return {'items': [candidate] if offset == 0 else []}

        with patch(CANDIDATES, new=fake):
            self.account._run_applicant_sync(jobs=self.job_a, trigger='manual')
            rec = self.env['hr.applicant'].search([('djinni_ref', '=', 'A-1')])
            # Recruiter cleans up the contact + name after the import.
            rec.write({'name': 'Recruiter Edited', 'email_from': 'corrected@example.com'})
            # Second sync of the very same candidate.
            log2 = self.account._run_applicant_sync(jobs=self.job_a, trigger='manual')

        self.assertEqual(self._count('A'), 1, 're-sync must not duplicate the candidate')
        self.assertEqual(rec.name, 'Recruiter Edited', 'name must not be overwritten')
        self.assertEqual(rec.email_from, 'corrected@example.com', 'email must not be overwritten')
        self.assertEqual(log2.new_count, 0, 'nothing new on the second pull')
        self.assertEqual(log2.skipped_count, 1, 'the existing candidate is counted as skipped')

    def test_same_candidate_on_two_vacancies_creates_two_records(self):
        """The same Djinni id surfacing on two vacancies yields two independent
        applicant records (keyed on djinni_ref + job_id), never a job bounce."""
        def fake(self, account_ref, endpoint, method='GET', params=None,
                 json=None, res_type='json'):
            offset = (params or {}).get('offset', 0)
            if offset:
                return {'items': []}
            # Same candidate id regardless of the vacancy.
            return {'items': [{
                'id': 'DUP-1', 'name': 'Multi Applier',
                'applied_at': '2024-01-01T00:00:00',
                'public_profile_url': 'https://djinni.co/q/DUP-1',
            }]}

        with patch(CANDIDATES, new=fake):
            self.account._run_applicant_sync(jobs=self.job_a | self.job_b, trigger='manual')

        recs = self.env['hr.applicant'].with_context(active_test=False).search(
            [('djinni_ref', '=', 'DUP-1')])
        self.assertEqual(len(recs), 2, 'one record per vacancy')
        self.assertEqual(set(recs.mapped('job_id')), {self.job_a, self.job_b})

    def _fake_one(self, candidate):
        """A `_djinni_api_request` stub returning a single candidate on page 0."""
        def fake(inner_self, account_ref, endpoint, method='GET', params=None,
                 json=None, res_type='json'):
            offset = (params or {}).get('offset', 0)
            return {'items': [candidate] if offset == 0 else []}
        return fake

    def test_email_match_adopts_existing_non_djinni_candidate(self):
        """A candidate added through another channel (no djinni_ref) is LINKED to
        Djinni by email instead of duplicated; its stage and source are kept and
        no acknowledgement email is sent."""
        interview = self.env.ref('hr_recruitment.stage_job1')
        manual = self.env['hr.applicant'].create({
            'name': 'Jane Manual', 'partner_name': 'Jane Manual',
            'email_from': 'jane@example.com', 'job_id': self.job_a.id,
            'stage_id': interview.id,
        })
        # Drain the manual record's OWN creation tracking now (Odoo 17 defers it
        # to the cursor precommit); otherwise it would fire inside the spy window
        # below and look like a stage email triggered by the sync.
        self.env.flush_all()
        self.env.cr.precommit.run()
        candidate = {
            'id': 'EM-1', 'name': 'Jane Djinni',
            'email': 'JANE@example.com',          # different case → still matches
            'phone': '+380501112233',
            'applied_at': '2024-01-01T00:00:00',
            'public_profile_url': 'https://djinni.co/q/EM-1',
            'cover_letter': 'Hi',
        }
        track = ('odoo.addons.hr_recruitment.models.hr_applicant.'
                 'Applicant._track_template')
        with patch(CANDIDATES, new=self._fake_one(candidate)), \
                patch(track, autospec=True, return_value={}) as track_spy:
            log = self.account._run_applicant_sync(jobs=self.job_a, trigger='manual')

        recs = self.env['hr.applicant'].with_context(active_test=False).search(
            [('job_id', '=', self.job_a.id),
             ('email_from', '=ilike', 'jane@example.com')])
        self.assertEqual(len(recs), 1, 'the existing record is adopted, not duplicated')
        self.assertEqual(recs, manual)
        self.assertEqual(manual.djinni_ref, 'EM-1', 'candidate is now linked to Djinni')
        self.assertEqual(manual.stage_id, interview,
                         'stage must be preserved (never reset to New)')
        self.assertEqual(manual.partner_name, 'Jane Manual',
                         'recruiter-owned name must not be overwritten')
        self.assertEqual(manual.partner_phone, '+380501112233',
                         'an empty contact field is back-filled from Djinni')
        self.assertEqual(log.new_count, 0)
        # The New-stage acknowledgement email fires only when `stage_id` is among
        # the tracked changes _track_template receives. Adoption never moves the
        # stage, so no call may carry a stage_id change (enrichment may still
        # trip _track_template for other tracked fields — that sends no email).
        stage_calls = [
            call for call in track_spy.call_args_list
            if 'stage_id' in (call.args[1] if len(call.args) > 1 else {})
        ]
        self.assertFalse(
            stage_calls,
            'an adopted (existing) candidate must NOT get the New-stage '
            'acknowledgement email (no stage_id tracking change)')

    def test_email_match_ambiguous_skips_and_logs(self):
        """>1 candidate in the job share the email (all without a Djinni id):
        the pull skips (no merge, no create) and records it in the sync log."""
        interview = self.env.ref('hr_recruitment.stage_job1')
        for n in ('Dup One', 'Dup Two'):
            self.env['hr.applicant'].create({
                'name': n, 'partner_name': n, 'email_from': 'dup@example.com',
                'job_id': self.job_a.id, 'stage_id': interview.id,
            })
        candidate = {
            'id': 'EM-2', 'name': 'Dup Djinni', 'email': 'dup@example.com',
            'applied_at': '2024-01-01T00:00:00',
            'public_profile_url': 'https://djinni.co/q/EM-2',
        }
        with patch(CANDIDATES, new=self._fake_one(candidate)):
            log = self.account._run_applicant_sync(jobs=self.job_a, trigger='manual')

        self.assertFalse(
            self.env['hr.applicant'].with_context(active_test=False).search(
                [('djinni_ref', '=', 'EM-2')]),
            'an ambiguous email match must not create a record')
        self.assertEqual(log.new_count, 0)
        self.assertEqual(log.skipped_count, 1)
        self.assertIn('Ambiguous email match', log.note or '')

    def test_email_match_different_email_creates_new_record(self):
        """A different email is not a match — a fresh record is created."""
        self.env['hr.applicant'].create({
            'name': 'Other', 'partner_name': 'Other',
            'email_from': 'other@example.com', 'job_id': self.job_a.id,
        })
        candidate = {
            'id': 'EM-3', 'name': 'New Person', 'email': 'new@example.com',
            'applied_at': '2024-01-01T00:00:00',
            'public_profile_url': 'https://djinni.co/q/EM-3',
        }
        with patch(CANDIDATES, new=self._fake_one(candidate)):
            log = self.account._run_applicant_sync(jobs=self.job_a, trigger='manual')

        rec = self.env['hr.applicant'].search([('djinni_ref', '=', 'EM-3')])
        self.assertTrue(rec, 'a different email must create a new record')
        self.assertEqual(log.new_count, 1)

    def test_email_match_ignores_records_that_already_have_a_djinni_ref(self):
        """Email adoption only targets ref-less records: a candidate already
        owned by a different Djinni id is left alone and a new record is made."""
        self.env['hr.applicant'].create({
            'name': 'Owned', 'partner_name': 'Owned',
            'email_from': 'owned@example.com', 'job_id': self.job_a.id,
            'djinni_ref': 'OLD-1',
        })
        candidate = {
            'id': 'EM-4', 'name': 'Owned Two', 'email': 'owned@example.com',
            'applied_at': '2024-01-01T00:00:00',
            'public_profile_url': 'https://djinni.co/q/EM-4',
        }
        with patch(CANDIDATES, new=self._fake_one(candidate)):
            self.account._run_applicant_sync(jobs=self.job_a, trigger='manual')

        self.assertTrue(
            self.env['hr.applicant'].search([('djinni_ref', '=', 'EM-4')]),
            'a record already owning a different Djinni ref must not be adopted')

    def _fake_any_job(self):
        """A `_djinni_api_request` stub that returns one candidate per vacancy.

        The candidate id is derived from the job ref in the endpoint so each
        vacancy yields a distinct, countable applicant.
        """
        def fake(inner_self, account_ref, endpoint, method='GET', params=None,
                 json=None, res_type='json'):
            offset = (params or {}).get('offset', 0)
            if offset:
                return {'items': []}
            ref = endpoint.split('/jobs/')[1].split('/')[0]
            return {'items': [{
                'id': 'J-%s' % ref,
                'name': 'Cand %s' % ref,
                'applied_at': '2024-01-01T00:00:00',
                'public_profile_url': 'https://djinni.co/q/%s' % ref,
            }]}
        return fake

    def _has_applicant_for_ref(self, ref):
        return bool(self.env['hr.applicant'].with_context(active_test=False).search_count(
            [('djinni_ref', '=', 'J-%s' % ref)]
        ))

    def test_cron_pulls_only_enabled_and_due_vacancies(self):
        """The cron tick respects the per-vacancy opt-in and the interval throttle."""
        now = fields.Datetime.now()
        # Enabled, never synced -> due -> pulled.
        on_due = self.env['hr.job'].create({
            'name': 'On Due', 'djinni_ref': '901',
            'djinni_account_id': self.account.id,
            'djinni_auto_sync_candidates': True, 'djinni_sync_interval': 'daily',
        })
        # Enabled, synced 5 min ago, daily interval -> NOT due -> skipped.
        on_recent = self.env['hr.job'].create({
            'name': 'On Recent', 'djinni_ref': '902',
            'djinni_account_id': self.account.id,
            'djinni_auto_sync_candidates': True, 'djinni_sync_interval': 'daily',
            'djinni_last_applicant_sync': now - timedelta(minutes=5),
        })
        # Disabled -> never pulled by the cron.
        off_job = self.env['hr.job'].create({
            'name': 'Off', 'djinni_ref': '903',
            'djinni_account_id': self.account.id,
            'djinni_auto_sync_candidates': False,
        })

        with patch(CANDIDATES, new=self._fake_any_job()):
            self.account.sync_applicant_list()  # cron path: enforce_interval=True

        self.assertTrue(self._has_applicant_for_ref('901'), 'due opted-in vacancy must sync')
        self.assertFalse(self._has_applicant_for_ref('902'), 'throttled vacancy must be skipped')
        self.assertFalse(self._has_applicant_for_ref('903'), 'opted-out vacancy must never sync')

    def test_manual_account_sync_bypasses_interval_but_not_optin(self):
        """`enforce_interval=False` pulls even recently-synced vacancies, yet still
        skips the ones that opted out."""
        now = fields.Datetime.now()
        on_recent = self.env['hr.job'].create({
            'name': 'On Recent', 'djinni_ref': '911',
            'djinni_account_id': self.account.id,
            'djinni_auto_sync_candidates': True, 'djinni_sync_interval': 'weekly',
            'djinni_last_applicant_sync': now - timedelta(minutes=1),
        })
        off_job = self.env['hr.job'].create({
            'name': 'Off', 'djinni_ref': '912',
            'djinni_account_id': self.account.id,
            'djinni_auto_sync_candidates': False,
        })

        with patch(CANDIDATES, new=self._fake_any_job()):
            self.account.sync_applicant_list(enforce_interval=False, trigger='manual')

        self.assertTrue(self._has_applicant_for_ref('911'), 'manual sync ignores the interval')
        self.assertFalse(self._has_applicant_for_ref('912'), 'manual sync still respects opt-out')

    def _patch_with_delay(self, calls):
        """Patch ``with_delay`` on djinni.account to capture the enqueue kwargs
        and run the worker synchronously, so a test without a live jobrunner can
        still assert both the queue shape and the resulting pull."""
        def mock_with_delay(account, *args, **kwargs):
            calls.append((account, kwargs))
            obj = MagicMock()

            def run_sync(*job_args, **job_kwargs):
                return account._job_account_applicant_sync(*job_args, **job_kwargs)

            obj._job_account_applicant_sync = MagicMock(side_effect=run_sync)
            return obj

        return patch.object(
            type(self.env['djinni.account']), 'with_delay', new=mock_with_delay)

    def test_cron_enqueues_one_queue_job_per_account(self):
        """The cron dispatcher delegates the pull to queue_job: exactly one job
        per account, on the dedicated channel, with a per-account identity_key
        (so a backed-up queue cannot double-pull and burn credits)."""
        self.env['hr.job'].create({
            'name': 'On Due', 'djinni_ref': '950',
            'djinni_account_id': self.account.id,
            'djinni_auto_sync_candidates': True, 'djinni_sync_interval': 'daily',
        })
        calls = []
        with self._patch_with_delay(calls), patch(CANDIDATES, new=self._fake_any_job()):
            self.account._enqueue_applicant_sync()

        self.assertEqual(len(calls), 1, 'exactly one job enqueued per account')
        _, kwargs = calls[0]
        self.assertEqual(kwargs.get('channel'), 'root.djinni')
        self.assertEqual(
            kwargs.get('identity_key'),
            'djinni_applicant_sync_%s' % self.account.id,
        )
        # The worker ran synchronously in the mock -> the due vacancy was pulled.
        self.assertTrue(self._has_applicant_for_ref('950'))

    def test_enqueued_worker_respects_optin_and_interval(self):
        """The queued worker re-resolves the due-set at execution time, so the
        opt-in and interval gates still bound the (paid) pull."""
        now = fields.Datetime.now()
        self.env['hr.job'].create({
            'name': 'Due', 'djinni_ref': '961',
            'djinni_account_id': self.account.id,
            'djinni_auto_sync_candidates': True, 'djinni_sync_interval': 'daily',
        })
        self.env['hr.job'].create({
            'name': 'Recent', 'djinni_ref': '962',
            'djinni_account_id': self.account.id,
            'djinni_auto_sync_candidates': True, 'djinni_sync_interval': 'daily',
            'djinni_last_applicant_sync': now - timedelta(minutes=5),
        })
        self.env['hr.job'].create({
            'name': 'Off', 'djinni_ref': '963',
            'djinni_account_id': self.account.id,
            'djinni_auto_sync_candidates': False,
        })
        calls = []
        with self._patch_with_delay(calls), patch(CANDIDATES, new=self._fake_any_job()):
            self.account._enqueue_applicant_sync()  # cron path: enforce_interval=True

        self.assertTrue(self._has_applicant_for_ref('961'), 'due opted-in vacancy pulled')
        self.assertFalse(self._has_applicant_for_ref('962'), 'throttled vacancy skipped')
        self.assertFalse(self._has_applicant_for_ref('963'), 'opted-out vacancy never pulled')

    def _import_one_candidate(self, job):
        """Run a one-candidate import into ``job`` and return the track spy."""
        candidate = {
            'id': 'A-1', 'name': 'Jane', 'applied_at': '2024-01-01T00:00:00',
            'public_profile_url': 'https://djinni.co/q/A-1',
            'email': 'jane@example.com',
        }

        def fake(self, account_ref, endpoint, method='GET', params=None,
                 json=None, res_type='json'):
            offset = (params or {}).get('offset', 0)
            return {'items': [candidate] if offset == 0 else []}

        track = ('odoo.addons.hr_recruitment.models.hr_applicant.'
                 'Applicant._track_template')
        with patch(CANDIDATES, new=fake), \
                patch(track, autospec=True, return_value={}) as track_spy:
            self.account._run_applicant_sync(jobs=job, trigger='manual')
        return track_spy

    def test_import_suppresses_email_when_vacancy_opts_in(self):
        """When the vacancy ticks ``djinni_suppress_new_email``, the stock stage
        acknowledgement must NOT be auto-mailed on import. The default stage
        carries a mail template, so Odoo's create-time field tracking would
        normally fire it; the sync then creates with ``mail_notrack=True`` to
        suppress exactly that email while keeping the chatter log. We assert the
        tracking-template hook never runs during the import."""
        stage = self.env.ref('hr_recruitment.stage_job0')
        self.assertTrue(
            stage.template_id,
            'precondition: the default stage must carry an email template, '
            'otherwise this test would pass vacuously',
        )
        self.job_a.djinni_suppress_new_email = True

        track_spy = self._import_one_candidate(self.job_a)

        rec = self.env['hr.applicant'].search([('djinni_ref', '=', 'A-1')])
        self.assertTrue(rec, 'the candidate must still be imported')
        self.assertEqual(
            rec.email_from, 'jane@example.com',
            'the candidate has a real email, so the template would have had a '
            'recipient — the suppression is what kept the mail away',
        )
        self.assertFalse(
            track_spy.called,
            'mail_notrack must skip the create-time stage template entirely, '
            'so no acknowledgement email is sent to the sourced candidate',
        )

    def test_import_sends_email_by_default(self):
        """With the default (opt-in off), importing a candidate fires the
        New-stage acknowledgement email like any other applicant — the
        create-time tracking-template hook must run."""
        self.assertFalse(
            self.job_a.djinni_suppress_new_email,
            'precondition: suppression is opt-in, so it must default to off',
        )

        track_spy = self._import_one_candidate(self.job_a)

        self.assertTrue(
            track_spy.called,
            'by default the imported candidate must receive the stage '
            'acknowledgement email (tracking-template hook runs)',
        )

    def test_ignored_offset_does_not_loop_forever(self):
        """If the API ignores `offset` (returns the same full page), we stop."""
        full_page = _make_candidates('A', 200)

        def fake(self, account_ref, endpoint, method='GET', params=None,
                 json=None, res_type='json'):
            return {'items': full_page}  # always the same page, ignores offset

        with patch(CANDIDATES, new=fake):
            log = self.account._run_applicant_sync(jobs=self.job_a, trigger='manual')

        self.assertEqual(self._count('A'), 200, 'deduped to a single page, no infinite loop')
        self.assertEqual(log.new_count, 200)

    def test_sync_job_list_never_creates_and_updates_only(self):
        """``sync_job_list`` refreshes linked vacancies but must NEVER create
        one — a Djinni vacancy that is not linked in Odoo is ignored, so other
        recruiters' vacancies can no longer leak into our pipeline."""
        self.job_a.djinni_account_id = self.account
        items = {'items': [
            {'id': '111', 'quizzes': []},   # linked -> job_a, must update
            {'id': '999', 'quizzes': []},   # not linked -> must be ignored
        ]}

        def fake(self, account_ref, endpoint, method='GET', params=None,
                 json=None, res_type='json'):
            return items

        before = self.env['hr.job'].with_context(active_test=False).search_count([])
        vals = 'odoo.addons.hr_djinni.models.djinni_account.DjinniAccount._djinni_job_payload_to_vals'
        with patch(CANDIDATES, new=fake), \
                patch(vals, autospec=True, return_value={'name': 'Updated Name'}):
            updated = self.account.sync_job_list()

        after = self.env['hr.job'].with_context(active_test=False).search_count([])
        self.assertEqual(before, after, 'sync must never create a new vacancy')
        self.assertIn(self.job_a, updated, 'the linked vacancy is refreshed')
        self.assertEqual(self.job_a.name, 'Updated Name')
        self.assertFalse(
            self.env['hr.job'].search([('djinni_ref', '=', '999')]),
            'a Djinni vacancy not linked in Odoo must be ignored, never created',
        )

    def test_unlink_disconnects_without_calling_djinni(self):
        """"Unlink from Djinni" clears the local link only — it must not touch
        the Djinni side (no API call), so another recruiter's vacancy is safe."""
        self.job_a.write({
            'djinni_account_id': self.account.id,
            'djinni_auto_sync_candidates': True,
        })
        with patch(CANDIDATES, autospec=True) as api:
            self.job_a.action_djinni_unlink()

        self.assertFalse(api.called, 'unlink must never call the Djinni API')
        self.assertFalse(self.job_a.djinni_ref)
        self.assertFalse(self.job_a.djinni_account_id)
        self.assertFalse(self.job_a.djinni_auto_sync_candidates)
