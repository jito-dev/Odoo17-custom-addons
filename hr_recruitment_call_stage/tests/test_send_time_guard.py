# -*- coding: utf-8 -*-
"""v17.0.22.0.0 — runtime send-time guard.

The permanent fix for "call-invite email sent without the Book-a-call
button": before any call-invite goes out, the resolved template is rendered
against the actual applicant and a real booking link is asserted. This file
pins:

* the guard helper (``_call_stage_booking_button_ok``) across its branches —
  including the prompt's key case "token present but booking_url resolves
  empty"; and
* the tracked-send integration: a call-invite template left wired to a stage
  that is NOT a Call Stage is suppressed (the production bug) rather than
  delivered button-less.
"""
from odoo.tests import tagged

from .common import CallStageTestCommon


# Shipped-style body: prefers the injected ctx URL, falls back to the field.
_BUTTON_BODY = (
    "<a t-att-href=\"ctx.get('booking_url') or object.booking_url\">"
    "Book a call</a>"
)
_REAL_BOOK_URL = 'https://o.jito.dev/book/abc123'


@tagged('post_install', '-at_install')
class TestSendTimeGuard(CallStageTestCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.applicant_model_id = cls.env.ref(
            'hr_recruitment.model_hr_applicant').id

    def _template(self, body):
        return self.env['mail.template'].create({
            'name': 'Guard test template CS',
            'model_id': self.applicant_model_id,
            'subject': 'X',
            'body_html': body,
        })

    # ---- guard helper, all branches ---------------------------------
    def test_guard_passes_with_real_url(self):
        tmpl = self._template(_BUTTON_BODY)
        applicant = self._make_applicant('Guard Anna CS', self.job_designer)
        self.assertTrue(
            applicant._call_stage_booking_button_ok(tmpl, _REAL_BOOK_URL),
            "a rendered button pointing at a real /book/ URL must pass")

    def test_guard_fails_token_present_but_url_empty(self):
        # The template references the token, but no URL resolves at render
        # time → the rendered button has an empty href → must NOT send.
        tmpl = self._template(_BUTTON_BODY)
        applicant = self._make_applicant('Guard Bohdan CS', self.job_designer)
        self.assertFalse(
            applicant._call_stage_booking_button_ok(tmpl, ''),
            "token present but empty booking URL must fail the guard")

    def test_guard_fails_without_button(self):
        tmpl = self._template('<p>No booking button at all.</p>')
        applicant = self._make_applicant('Guard Clara CS', self.job_designer)
        self.assertFalse(
            applicant._call_stage_booking_button_ok(tmpl, _REAL_BOOK_URL),
            "a body that renders no booking anchor must fail the guard")

    # ---- tracked-send integration: the production bug ----------------
    def test_track_suppresses_button_template_on_non_call_stage(self):
        # A call-invite template wired to a stage that is NOT a Call Stage
        # (e.g. 'Is Call Stage' was un-ticked) must be suppressed, not sent
        # button-less, and the recruiter must be alerted.
        tmpl = self._template(_BUTTON_BODY)
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({'mail_template_id': tmpl.id})  # NOT a call stage
        self.assertFalse(cfg.is_call_stage)

        applicant = self._make_applicant('Guard Dmytro CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        before = self.env['mail.activity'].search_count([
            ('res_id', '=', applicant.id),
            ('res_model', '=', 'hr.applicant'),
        ])
        res = applicant._track_template({'stage_id'})
        self.assertNotIn('stage_id', res,
            "button-less call-invite send must be suppressed")
        after = self.env['mail.activity'].search_count([
            ('res_id', '=', applicant.id),
            ('res_model', '=', 'hr.applicant'),
        ])
        self.assertGreater(after, before,
            "recruiter must be alerted with a follow-up activity")

    def test_track_allows_plain_non_booking_template(self):
        # A normal stage email with no booking button must pass through
        # untouched on a non-call stage.
        tmpl = self._template('<p>Thanks for applying — we will be in touch.</p>')
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({'mail_template_id': tmpl.id})
        applicant = self._make_applicant('Guard Eva CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        res = applicant._track_template({'stage_id'})
        self.assertIn('stage_id', res,
            "a plain (non-booking) stage email must still be sent")
