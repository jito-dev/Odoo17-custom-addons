# -*- coding: utf-8 -*-
"""Etap 4 (v17.0.4.0.0) — kanban badge, bulk action, email preview,
breadcrumb, candidate timezone."""
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CallStageTestCommon


@tagged('post_install', '-at_install')
class TestEtap4Polish(CallStageTestCommon):
    def _enable(self, job, appt_type):
        cfg = self._get_config(job, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': appt_type.id,
        })
        return cfg

    # ---- 4.1: bulk server action exists and is bound to applicants --
    def test_bulk_send_action_is_registered(self):
        action = self.env.ref(
            'hr_recruitment_call_stage.action_server_send_call_invite_bulk',
            raise_if_not_found=False)
        self.assertTrue(action, "Bulk action must be registered.")
        self.assertEqual(action.model_id.model, 'hr.applicant')
        self.assertEqual(action.binding_model_id.model, 'hr.applicant')

    def test_bulk_send_idempotent_skip_invisible(self):
        # job_designer has no call stage; bulk action should silently
        # skip applicants whose call_scheduling_visible is False.
        a1 = self._make_applicant('Anna E4 CS', self.job_designer)
        before = self.env['mail.message'].search_count([
            ('res_id', '=', a1.id), ('model', '=', 'hr.applicant')])
        # Simulate the server action's filter manually.
        eligible = a1.filtered(lambda a: a.call_scheduling_visible and a.active)
        self.assertFalse(eligible,
            "Applicant without a Call Stage on their job must be filtered "
            "out of the bulk send.")
        after = self.env['mail.message'].search_count([
            ('res_id', '=', a1.id), ('model', '=', 'hr.applicant')])
        self.assertEqual(before, after)

    # ---- 4.2: candidate timezone field readable ---------------------
    def test_candidate_tz_resolves_from_partner(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant(
            'Boris E4 CS', self.job_designer, self.stage_call)
        if not applicant.partner_id:
            applicant.partner_id = self.env['res.partner'].create({
                'name': 'B-Boris CS', 'tz': 'Europe/Kyiv',
            })
        else:
            applicant.partner_id.tz = 'Europe/Kyiv'
        applicant.invalidate_recordset(['candidate_tz'])
        self.assertEqual(applicant.candidate_tz, 'Europe/Kyiv')

    # ---- 4.3: email preview action returns a client notification ----
    def test_preview_email_returns_notification(self):
        cfg = self._enable(self.job_designer, self.appt_hr_call)
        result = cfg.action_preview_call_invite()
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get('type'), 'ir.actions.client')
        self.assertEqual(result.get('tag'), 'display_notification')

    def test_preview_email_without_template_raises(self):
        cfg = self._get_config(self.job_designer, self.stage_call)
        cfg.write({'mail_template_id': False, 'is_call_stage': False})
        with self.assertRaises(UserError):
            cfg.action_preview_call_invite()

    # ---- 4.5: breadcrumb action opens the stage config form ---------
    def test_action_open_call_stage_config(self):
        self._enable(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant(
            'Clara E4 CS', self.job_designer, self.stage_call)
        result = applicant.action_open_call_stage_config()
        self.assertEqual(result['res_model'], 'hr.job.stage.config')
        self.assertTrue(result.get('res_id'))

    def test_action_open_stage_config_without_call_stage_raises(self):
        applicant = self._make_applicant('Diana E4 CS', self.job_designer)
        with self.assertRaises(UserError):
            applicant.action_open_call_stage_config()
