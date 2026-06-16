# -*- coding: utf-8 -*-
"""v17.0.23.0.0 — Call Stage Settings dialog: readiness compute, status-chip
deep-links, test toolbar and the email-preview action.

The OWL iframe widget itself is JS (not unit-tested here); these tests pin the
server-side contracts the dialog relies on.
"""
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CallStageTestCommon


@tagged('post_install', '-at_install')
class TestCallStageSettingsUI(CallStageTestCommon):
    def _enable(self, template=None, recruiter=False):
        cfg = self._get_config(self.job_designer, self.stage_call)
        vals = {
            'is_call_stage': True,
            'booking_appointment_type_id': self.appt_hr_call.id,
        }
        if template:
            vals['mail_template_id'] = template.id
        cfg.write(vals)
        if recruiter:
            # v17.0.24.0.0: booking staff now lives on the Appointment Type
            # directly (the recruiter_user_ids sync was neutralised). Seed a
            # real internal (share=False) user — the test superuser is filtered
            # out by the staff field's share domain.
            self.appt_hr_call.sudo().staff_user_ids = [
                (6, 0, [self.env.ref('base.user_admin').id])]
        return cfg

    # ---- readiness ---------------------------------------------------
    def test_ready_when_fully_configured(self):
        cfg = self._enable(recruiter=True)
        cfg.invalidate_recordset()
        self.assertTrue(cfg.call_check_booking_button)
        self.assertTrue(cfg.call_check_appointment)
        self.assertTrue(cfg.call_check_staff)
        self.assertEqual(cfg.call_readiness_state, 'ready')

    def test_needs_attention_without_staff(self):
        cfg = self._enable()
        # Clear booking-calendar staff → non-blocking warning.
        self.appt_hr_call.sudo().staff_user_ids = [(5, 0, 0)]
        cfg.invalidate_recordset()
        self.assertFalse(cfg.call_check_staff)
        self.assertEqual(cfg.call_readiness_state, 'needs_attention')

    def test_wont_send_when_button_missing(self):
        # A button-less template can only reach a saved Call Stage as legacy
        # data (the constraint blocks it on save), so reproduce via raw SQL.
        cfg = self._enable()
        button_less = self.env['mail.template'].create({
            'name': 'No button CS',
            'model_id': self.env.ref('hr_recruitment.model_hr_applicant').id,
            'subject': 'X',
            'body_html': '<p>No button.</p>',
        })
        # Flush pending ORM writes (e.g. the auto-filled template) to DB
        # BEFORE the raw SQL, so the SQL value sticks and is not clobbered by
        # a later flush. (Do not rely on an incidental flush from elsewhere.)
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE hr_job_stage_config SET mail_template_id=%s WHERE id=%s",
            (button_less.id, cfg.id))
        cfg.invalidate_recordset()
        self.assertFalse(cfg.call_check_booking_button)
        self.assertEqual(cfg.call_readiness_state, 'wont_send')

    def test_non_call_stage_has_no_state(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.invalidate_recordset()
        self.assertFalse(cfg.call_readiness_state)

    # ---- preview action ---------------------------------------------
    def test_preview_email_opens_dialog_with_button(self):
        cfg = self._enable()
        action = cfg.action_preview_email()
        self.assertEqual(action['res_model'], 'hr.call.stage.preview')
        self.assertEqual(action['target'], 'new')
        preview = self.env['hr.call.stage.preview'].browse(action['res_id'])
        self.assertTrue(preview.exists())
        self.assertTrue(preview.has_button,
            "shipped template carries the booking button")
        self.assertTrue(preview.rendered_body)

    def test_preview_back_to_config_reopens_settings(self):
        cfg = self._enable()
        preview = self.env['hr.call.stage.preview'].browse(
            cfg.action_preview_email()['res_id'])
        back = preview.action_back_to_config()
        self.assertEqual(back['type'], 'ir.actions.act_window')
        self.assertEqual(back['res_model'], 'hr.job.stage.config')
        self.assertEqual(back['res_id'], cfg.id)
        self.assertEqual(back['target'], 'new')

    def test_preview_back_to_config_without_config_just_closes(self):
        # Defensive: a preview with no originating config must not crash.
        preview = self.env['hr.call.stage.preview'].create({})
        self.assertEqual(
            preview.action_back_to_config()['type'],
            'ir.actions.act_window_close')

    # ---- per-job override is auto-filled (issue: empty template) -----
    def test_override_template_autofilled_on_enable(self):
        cfg = self._enable()
        self.assertEqual(
            cfg.mail_template_id,
            self.env.ref(
                'hr_recruitment_call_stage.mail_template_call_invite_generic'),
            "enabling a Call Stage pre-fills the per-job override so the "
            "field is never shown empty")

    # ---- deep-link chips --------------------------------------------
    def test_chip_actions_open_records(self):
        cfg = self._enable(recruiter=True)
        tmpl_act = cfg.action_open_call_template()
        self.assertEqual(tmpl_act['res_model'], 'mail.template')
        appt_act = cfg.action_open_appointment_type()
        self.assertEqual(appt_act['res_model'], 'appointment.type')
        self.assertEqual(appt_act['res_id'], self.appt_hr_call.id)

    def test_open_booking_page_returns_url(self):
        cfg = self._enable()
        action = cfg.action_open_booking_page()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertEqual(action['target'], 'new')
        self.assertIn('/appointment/%s' % self.appt_hr_call.id, action['url'])

    # ---- test toolbar ------------------------------------------------
    def test_send_test_email_to_current_user(self):
        self.env.user.email = 'recruiter.cs@example.invalid'
        cfg = self._enable()
        self._make_applicant('Sample CS', self.job_designer, self.stage_call)
        result = cfg.action_send_test_email()
        # force_send=True + the template's auto_delete means the mail.mail is
        # gone after sending, so assert on the success notification instead.
        self.assertEqual(result['tag'], 'display_notification')
        self.assertEqual(result['params']['type'], 'success')
        self.assertIn('recruiter.cs@example.invalid', result['params']['message'])

    def test_send_test_email_without_applicant_still_sends(self):
        self.env.user.email = 'recruiter.cs@example.invalid'
        cfg = self._enable()
        Applicant = self.env['hr.applicant']
        before = Applicant.search_count([('job_id', '=', cfg.job_id.id)])
        # No applicant on this job → renders against an ephemeral candidate
        # created inside a rolled-back savepoint; the [TEST] copy still reaches
        # the recruiter, but the throwaway record must NOT be persisted.
        result = cfg.action_send_test_email()
        self.assertEqual(result['tag'], 'display_notification')
        self.assertEqual(result['params']['type'], 'success')
        self.assertIn(
            'recruiter.cs@example.invalid', result['params']['message'])
        after = Applicant.search_count([('job_id', '=', cfg.job_id.id)])
        self.assertEqual(
            after, before,
            "ephemeral test applicant should be rolled back, not persisted")
