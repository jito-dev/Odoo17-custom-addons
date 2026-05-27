# -*- coding: utf-8 -*-
"""Wizard inherit: surface call-stage fields in the "Add job-specific stage"
flow so a recruiter can configure a Call Stage at creation time, not as a
follow-up edit in the popup.

Mirrors the popup form (`view_hr_job_stage_config_form_call`):
  * `is_call_stage` toggle
  * `booking_appointment_type_id` (required when toggle on)
  * `call_booked_stage_id` (auto-managed; rarely overridden)
  * `mail_template_id` auto-fills with the shipped call-invite template on
    toggle-on (onchange path), respecting any pre-existing user pick.

The created `hr.job.stage.config` row also receives the call-stage payload
via `action_create` extension, so the config row is born fully configured.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


_CALL_INVITE_TEMPLATE_XMLID = (
    'hr_recruitment_call_stage.mail_template_call_invite_generic'
)


class HrJobStageCreateWizard(models.TransientModel):
    _inherit = 'hr.job.stage.create.wizard'

    is_call_stage = fields.Boolean(
        string='Is Call Stage',
        help='Tick to mark the new stage as a call-scheduling stage. '
             'The shipped call-invite template will be pre-selected and an '
             'Appointment Type becomes required.')
    booking_appointment_type_id = fields.Many2one(
        'appointment.type', string='Appointment Type',
        ondelete='set null',
        help='Odoo Appointments type used to mint the per-candidate booking '
             'URL injected into the assigned email template at render time.')
    call_booked_stage_id = fields.Many2one(
        'hr.recruitment.stage', string='Move to after booking',
        ondelete='set null',
        help='Stage the applicant is moved to once they confirm a slot. '
             "Left empty here — the foundation auto-populates it to the "
             'shipped "Call Booked" stage on first save.')
    recruiter_user_ids = fields.Many2many(
        'res.users', 'hr_job_stage_create_wizard_recruiter_user_rel',
        'wizard_id', 'user_id',
        string='Booking calendars (internal staff)',
        domain="[('share', '=', False)]",
        help="Recruiters whose Odoo calendars feed the booking pool. "
             "Added (UNION) to the appointment type's staff_user_ids on "
             "save. Leave empty to keep the appointment type's existing "
             'staff list as-is.')

    @api.onchange('is_call_stage')
    def _onchange_is_call_stage_autofill_template(self):
        # Mirrors the server-side auto-fill in hr.job.stage.config.create/write.
        # Onchange runs in form context only — recruiters using the wizard UI
        # see the template pre-filled the moment they toggle on. Programmatic
        # callers go through action_create, where the same fallback applies
        # on the config row write.
        if self.is_call_stage and not self.mail_template_id:
            default_template = self.env.ref(
                _CALL_INVITE_TEMPLATE_XMLID, raise_if_not_found=False)
            if default_template:
                self.mail_template_id = default_template

    def action_create(self):
        self.ensure_one()
        if self.is_call_stage and not self.booking_appointment_type_id:
            raise UserError(_(
                "Tick 'Is Call Stage' requires an Appointment Type. Pick one "
                "or untick the call-stage option."))
        # Let super create the stage and the config row with the base payload
        # (name, sequence, mail_template_id, requirements, test_task, links).
        result = super().action_create()
        if not self.is_call_stage:
            return result
        # Find the freshly-created config row and stamp the call-stage payload
        # onto it. The hr.job.stage.config write override will resolve the
        # companion "Call Booked" linking. Mail template is already on the
        # row (super's action_create copied wizard.mail_template_id, which
        # the onchange auto-filled).
        Stage = self.env['hr.recruitment.stage'].sudo()
        # Latest stage created with this exact (job, name) — action_create
        # makes one stage per wizard run, so 'most recent matching' is safe.
        stage = Stage.search([
            ('job_ids', 'in', self.job_id.id),
            ('name', '=', self.name),
        ], limit=1, order='id desc')
        if not stage:
            return result
        Config = self.env['hr.job.stage.config'].sudo()
        config = Config.search([
            ('job_id', '=', self.job_id.id),
            ('stage_id', '=', stage.id),
        ], limit=1)
        if not config:
            return result
        config.write({
            'is_call_stage': True,
            'booking_appointment_type_id': self.booking_appointment_type_id.id,
            'call_booked_stage_id': (
                self.call_booked_stage_id.id or False),
            'recruiter_user_ids': [(6, 0, self.recruiter_user_ids.ids)],
        })
        return result
