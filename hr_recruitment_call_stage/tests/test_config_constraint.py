# -*- coding: utf-8 -*-
"""v17.0.22.0.0 — config-time constraint that blocks saving a broken Call
Stage (so a button-less / mis-wired invite can never reach production).

Companion to the runtime send-time guard in ``test_send_time_guard``: this
file pins the *save-time* gate on ``hr.job.stage.config``.
"""
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import CallStageTestCommon


@tagged('post_install', '-at_install')
class TestCallStageConfigConstraint(CallStageTestCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.applicant_model_id = cls.env.ref(
            'hr_recruitment.model_hr_applicant').id

    def _template(self, body):
        return self.env['mail.template'].create({
            'name': 'Constraint test template CS',
            'model_id': self.applicant_model_id,
            'subject': 'X',
            'body_html': body,
        })

    def test_missing_booking_button_blocks_save(self):
        tmpl = self._template('<p>Welcome, no booking button here.</p>')
        cfg = self._get_config(self.job_designer, self.stage_call)
        with self.assertRaises(ValidationError):
            cfg.write({
                'is_call_stage': True,
                'booking_appointment_type_id': self.appt_hr_call.id,
                'mail_template_id': tmpl.id,
            })

    def test_near_miss_typo_blocks_save_with_hint(self):
        # `obj.booking_url` instead of `object.booking_url`.
        tmpl = self._template('<a t-att-href="obj.booking_url">Book</a>')
        cfg = self._get_config(self.job_designer, self.stage_call)
        with self.assertRaises(ValidationError) as cm:
            cfg.write({
                'is_call_stage': True,
                'booking_appointment_type_id': self.appt_hr_call.id,
                'mail_template_id': tmpl.id,
            })
        self.assertIn('object.booking_url', str(cm.exception),
            "the error should point the recruiter at the correct token")

    def test_valid_button_template_saves(self):
        tmpl = self._template(
            '<a t-att-href="object.booking_url">Book a call</a>')
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'mail_template_id': tmpl.id,
        })
        self.assertTrue(cfg.is_call_stage)
        self.assertEqual(cfg.mail_template_id, tmpl)

    def test_ctx_token_template_saves(self):
        # The shipped/legacy form `ctx.get('booking_url')` is also valid.
        tmpl = self._template(
            "<a t-att-href=\"ctx.get('booking_url') or object.booking_url\">"
            "Book a call</a>")
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'mail_template_id': tmpl.id,
        })
        self.assertTrue(cfg.is_call_stage)

    # NOTE: the "Move to after booking" destination carries NO safeguard
    # anymore (it is fully auto-managed), so there are no destination-blocks
    # tests here — setting any stage must NOT raise.
    def test_destination_is_not_validated(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        # Even pointing the destination at the Call Stage itself must save fine.
        cfg.write({'call_booked_stage_id': self.stage_call.id})
        self.assertEqual(cfg.call_booked_stage_id, self.stage_call)
