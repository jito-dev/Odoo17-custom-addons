# -*- coding: utf-8 -*-
"""Etap 6 (v17.0.5.0.0) — regression tests for the stale-body sweeper.

The migration in ``migrations/17.0.5.0.0/pre-migrate.py`` rewrites any
``mail.template`` whose ``body_html`` still contains the legacy
"Booking link unavailable" paragraph. These tests cover:

1. A duplicated template with the legacy body gets rewritten by the
   migrate function.
2. A genuinely customised template (no legacy marker) is preserved
   byte-identical.
3. End-to-end render path: an applicant with ``manual_meeting_url``
   set, sent via ``action_send_invite_email``, produces a queued
   ``mail.mail`` whose body contains the pasted URL.
"""
import importlib.util
import os

from odoo.tests import tagged

from .common import CallStageTestCommon


_LEGACY_BODY_V17_0_1_1_0 = """
<div style="margin:0px;padding:0px;font-size:14px;">
    <p>Hi <t t-out="object.partner_name or object.name or ''"/>,</p>
    <p>
        Thanks again for your interest in the
        <strong><t t-out="object.job_id.name or 'role'"/></strong>
        position. Please pick a slot that works for you:
    </p>
    <p t-if="ctx.get('booking_url')" style="margin:24px 0;">
        <a t-att-href="ctx.get('booking_url')"
           style="background:#714B67;color:#ffffff;padding:12px 22px;
                  border-radius:4px;text-decoration:none;
                  display:inline-block;font-weight:600;">
            Book a call
        </a>
    </p>
    <p t-if="not ctx.get('booking_url')" style="color:#888;">
        (Booking link unavailable - please reply to this email and we
        will schedule manually.)
    </p>
    <p>
        Looking forward to talking with you.
    </p>
    <p>
        Best,<br/>
        <t t-out="object.user_id.name or object.company_id.name or ''"/>
    </p>
</div>
""".strip()


def _load_migration_module():
    """Import the pre-migrate script as a module so we can call
    ``migrate(cr, version)`` directly inside a test transaction.
    """
    here = os.path.dirname(__file__)
    path = os.path.normpath(os.path.join(
        here, '..', 'migrations', '17.0.5.0.0', 'pre-migrate.py'))
    spec = importlib.util.spec_from_file_location(
        'hr_recruitment_call_stage_17_0_5_0_0_pre_migrate', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged('post_install', '-at_install')
class TestEtap6BodyRefresh(CallStageTestCommon):
    def setUp(self):
        super().setUp()
        self.MailTemplate = self.env['mail.template']
        self.applicant_model_id = self.env.ref(
            'hr_recruitment.model_hr_applicant').id
        self._migration = _load_migration_module()

    # ---- 6.1: legacy duplicate is refreshed -------------------------
    def test_legacy_duplicate_is_refreshed(self):
        dup = self.MailTemplate.create({
            'name': 'Legacy duplicate CS',
            'model_id': self.applicant_model_id,
            'subject': 'Schedule your call for {{ object.job_id.name or "" }}',
            'body_html': _LEGACY_BODY_V17_0_1_1_0,
        })
        # Sanity: legacy marker is present before the sweep.
        self.assertIn('Booking link unavailable', dup.body_html)

        self._migration.migrate(self.env.cr, '17.0.5.0.0')
        dup.invalidate_recordset(['body_html'])

        body = dup.body_html or ''
        self.assertNotIn('Booking link unavailable', body,
            "legacy fallback paragraph must be wiped after sweep")
        self.assertIn('object.booking_url', body,
            "rewritten body must read object.booking_url")
        self.assertIn('Book a call', body,
            "rewritten body must keep the button label")

    # ---- 6.2: non-legacy bodies are preserved ------------------------
    def test_customised_body_is_preserved(self):
        custom = self.MailTemplate.create({
            'name': 'Custom CS',
            'model_id': self.applicant_model_id,
            'subject': 'X',
            'body_html': '<p>Hello — our scheduling link will follow.</p>',
        })
        before = custom.body_html

        self._migration.migrate(self.env.cr, '17.0.5.0.0')
        custom.invalidate_recordset(['body_html'])

        self.assertEqual(custom.body_html, before,
            "non-legacy body must not be touched by the sweep")

    # ---- 6.3: idempotent re-run --------------------------------------
    def test_sweep_is_idempotent(self):
        dup = self.MailTemplate.create({
            'name': 'Legacy duplicate CS idemp',
            'model_id': self.applicant_model_id,
            'subject': 'X',
            'body_html': _LEGACY_BODY_V17_0_1_1_0,
        })

        self._migration.migrate(self.env.cr, '17.0.5.0.0')
        dup.invalidate_recordset(['body_html'])
        first_pass = dup.body_html

        # Second run on an already-refreshed DB must be a no-op.
        self._migration.migrate(self.env.cr, '17.0.5.0.0')
        dup.invalidate_recordset(['body_html'])
        self.assertEqual(dup.body_html, first_pass,
            "second migration pass must produce identical body")

    # ---- 6.4: end-to-end manual-url render ---------------------------
    def test_action_send_invite_renders_manual_url(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        applicant = self._make_applicant(
            'Polina CS', self.job_designer, self.stage_call)
        manual_url = 'https://meet.example.com/jito-polina-cs'
        applicant.manual_meeting_url = manual_url

        # booking_url compute must surface the manual override.
        self.assertEqual(applicant.booking_url, manual_url)

        # Sweep first so we hit the freshly-loaded shipped body even on
        # installations that migrated through a customised body path.
        self._migration.migrate(self.env.cr, '17.0.5.0.0')

        mails_before = self.env['mail.mail'].sudo().search([
            ('model', '=', 'hr.applicant'),
            ('res_id', '=', applicant.id),
        ])
        applicant.action_send_invite_email()
        mails_after = self.env['mail.mail'].sudo().search([
            ('model', '=', 'hr.applicant'),
            ('res_id', '=', applicant.id),
        ])
        new_mails = mails_after - mails_before
        self.assertTrue(new_mails,
            "action_send_invite_email must queue a mail.mail")
        body = new_mails[-1].body_html or new_mails[-1].body or ''
        self.assertIn(manual_url, body,
            "pasted manual URL must appear in the rendered email body")
        self.assertNotIn('Booking link unavailable', body,
            "fallback paragraph must never reach the candidate")
