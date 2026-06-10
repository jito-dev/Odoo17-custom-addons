# -*- coding: utf-8 -*-
"""Etap 1 (v17.0.1.2.0) — regression tests for the fundamentals cleanup.

Each test pins one of the P0 fixes documented in
``docs/call_stage_improvement_plan.md`` §"Етап 1".
"""
from datetime import datetime, timedelta

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CallStageTestCommon


@tagged('post_install', '-at_install')
class TestEtap1Fixes(CallStageTestCommon):
    def _enable(self, job, appt_type):
        cfg = self._get_config(job, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': appt_type.id,
        })
        return cfg

    def _make_booked_invite(self, applicant, appt_type):
        return applicant._get_or_create_booking_invite(appt_type)

    def _create_event(self, applicant, appt_type, invite):
        start = datetime.now() + timedelta(days=1)
        return self.CalendarEvent.create({
            'name': 'X',
            'start': start,
            'stop': start + timedelta(minutes=30),
            'appointment_type_id': appt_type.id,
            'appointment_invite_id': invite.id,
            'partner_ids': [(6, 0, applicant.partner_id.ids)]
                           if applicant.partner_id else False,
        })

    # ---- 1.2 (preserved through Etap 2 via @api.ondelete on appointment.type):
    # deleting an appointment type with applicant-linked invites is blocked.
    def test_appointment_type_delete_blocked_when_invite_exists(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant(
            'Anna CS', self.job_designer, self.stage_call)
        self._make_booked_invite(applicant, self.appt_hr_call)
        with self.assertRaises(UserError):
            self.appt_hr_call.unlink()

    # ---- 1.3: archived / refused applicant cannot resurrect ----------
    def test_archived_applicant_not_advanced_on_booking(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant(
            'Boris CS', self.job_designer, self.stage_call)
        link = self._make_booked_invite(applicant, self.appt_hr_call)
        applicant.active = False
        self._create_event(applicant, self.appt_hr_call, link)
        applicant.invalidate_recordset(['stage_id'])
        # Stage MUST stay where the recruiter put the (archived) applicant,
        # not jump to Call Booked.
        self.assertEqual(applicant.stage_id, self.stage_call)

    def test_refused_applicant_not_advanced_on_booking(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant(
            'Clara CS', self.job_designer, self.stage_call)
        link = self._make_booked_invite(applicant, self.appt_hr_call)
        reason = self.env['hr.applicant.refuse.reason'].search([], limit=1)
        if not reason:
            reason = self.env['hr.applicant.refuse.reason'].create({
                'name': 'Test refuse CS',
            })
        applicant.refuse_reason_id = reason.id
        self._create_event(applicant, self.appt_hr_call, link)
        applicant.invalidate_recordset(['stage_id'])
        self.assertEqual(applicant.stage_id, self.stage_call)

    # ---- 1.4: multi-company ICS summary ------------------------------
    def test_ics_summary_uses_applicant_company(self):
        company_a = self.env['res.company'].create({'name': 'Brand-A CS'})
        company_b = self.env['res.company'].create({'name': 'Brand-B CS'})
        # Job belongs to company B; request env is company A.
        job_b = self.Job.create({
            'name': 'Designer B CS',
            'company_id': company_b.id,
        })
        cfg = self.Config.search([
            ('job_id', '=', job_b.id),
            ('stage_id', '=', self.stage_call.id),
        ], limit=1)
        if not cfg:
            # Foundation may not have backfilled for this job/stage pair —
            # create directly for the test.
            cfg = self.Config.create({
                'job_id': job_b.id,
                'stage_id': self.stage_call.id,
            })
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        })
        applicant = self.Applicant.with_company(company_b).create({
            'name': 'Diana CS',
            'partner_name': 'Diana CS',
            'job_id': job_b.id,
            'company_id': company_b.id,
            'stage_id': self.stage_call.id,
        })
        link = self._make_booked_invite(applicant, self.appt_hr_call)
        event = self._create_event(applicant, self.appt_hr_call, link)
        # Render summary in request env of company A — must still say B.
        summary = event.with_company(company_a)._get_customer_summary()
        self.assertIn('Brand-B CS', summary)
        self.assertNotIn('Brand-A CS', summary)

    # ---- 1.5: template no longer ships the fallback paragraph --------
    def test_shipped_template_has_no_fallback_paragraph(self):
        tmpl = self.env.ref(
            'hr_recruitment_call_stage.mail_template_call_invite_generic')
        body = tmpl.body_html or ''
        self.assertNotIn('Booking link unavailable', body)
        self.assertNotIn('please reply to this email and we', body)

    # ---- 1.5: missing booking link -> NO email sent + recruiter alert
    def test_missing_appointment_type_suppresses_send_and_alerts(self):
        template = self.env['mail.template'].create({
            'name': 'CI Template CS',
            'model_id': self.env.ref('hr_recruitment.model_hr_applicant').id,
            'subject': 'X',
            'body_html': '<p>hi</p>',
        })
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
            'mail_template_id': template.id,
        })
        # Force a degenerate legacy state: is_call_stage=True but no appt
        # type. Bypass the constrains by going through raw SQL.
        self.env.cr.execute(
            "UPDATE hr_job_stage_config SET booking_appointment_type_id=NULL "
            "WHERE id=%s",
            (cfg.id,),
        )
        cfg.invalidate_recordset(['booking_appointment_type_id'])
        applicant = self._make_applicant(
            'Eva CS', self.job_designer)
        applicant.stage_id = self.stage_call.id
        before = self.env['mail.activity'].search_count([
            ('res_id', '=', applicant.id),
            ('res_model', '=', 'hr.applicant'),
        ])
        res = applicant._track_template({'stage_id'})
        # `stage_id` entry must be popped so the email never sends.
        self.assertNotIn('stage_id', res)
        after = self.env['mail.activity'].search_count([
            ('res_id', '=', applicant.id),
            ('res_model', '=', 'hr.applicant'),
        ])
        self.assertGreater(after, before,
            "recruiter activity should have been scheduled")
