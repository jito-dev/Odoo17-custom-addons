# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    # ------------------------------------------------------------------
    # Bridge: surface the booked Google Meet link + booking lifecycle
    # ------------------------------------------------------------------
    # `hr_recruitment_call_stage` owns `booking_url` (how to BOOK) and
    # `call_status`. This bridge adds `meet_url` (where the call HAPPENS),
    # the current booked slot, and the cancel/reschedule signals that drive
    # the two new call_status states.

    meet_url = fields.Char(
        string='Meeting link',
        compute='_compute_meet_url',
        store=False,
        help='Google Meet link of the booked calendar event for this '
             'applicant. Empty until a slot is booked. Read straight off '
             'calendar.event.videocall_location — never re-minted here.')

    call_booked_start = fields.Datetime(
        string='Booked slot',
        copy=False,
        help='Start of the currently booked call slot. Stamped on booking '
             'and updated on reschedule so the recruiter sees the live time '
             'without opening the calendar event.')

    call_cancelled = fields.Boolean(
        string='Call cancelled',
        copy=False,
        help='Set when the booked call is cancelled (candidate via the '
             'public page, or recruiter by archiving the event). Cleared '
             'automatically when a new slot is booked.')

    call_rescheduled = fields.Boolean(
        string='Call rescheduled',
        copy=False,
        help='Set when the booked call has been moved at least once. Drives '
             'the `rescheduled` call_status flavour; reset on a clean first '
             'booking.')

    call_status = fields.Selection(
        selection_add=[
            ('rescheduled', 'Rescheduled'),
            ('cancelled', 'Cancelled'),
        ],
        # call_status is a stored *computed* field with no default, so
        # 'set default' is rejected. 'set null' is safe — the value is
        # recomputed anyway after the selection key is removed.
        ondelete={'rescheduled': 'set null', 'cancelled': 'set null'},
    )

    @api.depends('job_id', 'stage_id', 'call_cancelled', 'manual_meeting_url')
    def _compute_meet_url(self):
        CalendarEvent = self.env['calendar.event'].sudo()
        for applicant in self:
            url = False
            invite = applicant._get_current_invite()
            if invite:
                event = CalendarEvent.search([
                    ('applicant_id', '=', applicant.id),
                    ('appointment_invite_id', '=', invite.id),
                    ('active', '=', True),
                ], limit=1)
                if event:
                    url = event.videocall_location or False
            applicant.meet_url = url

    # Restate the parent's dependencies (overriding the compute replaces the
    # field's trigger set) and add the two lifecycle signals.
    @api.depends('job_id', 'stage_id', 'call_outcome', 'manual_meeting_url',
                 'call_cancelled', 'call_rescheduled')
    def _compute_call_status(self):
        # Let the call_stage compute run first (it owns the base derivation
        # from invite / event / outcome), then layer the lifecycle states.
        super()._compute_call_status()
        for applicant in self:
            # Recruiter-set terminal outcomes win — never mask attended /
            # no_show with a lifecycle flag.
            if applicant.call_outcome in ('attended', 'no_show'):
                continue
            if applicant.call_cancelled:
                applicant.call_status = 'cancelled'
            elif applicant.call_status == 'booked' and applicant.call_rescheduled:
                applicant.call_status = 'rescheduled'

    def action_join_call(self):
        """Open the booked Google Meet link in a new browser tab."""
        self.ensure_one()
        if not self.meet_url:
            return False
        return {
            'type': 'ir.actions.act_url',
            'url': self.meet_url,
            'target': 'new',
        }

    # ------------------------------------------------------------------
    # Booking lifecycle transitions (called from calendar.event hooks)
    # ------------------------------------------------------------------
    def _call_meet_on_booking(self, event):
        """A fresh calendar event was booked for this applicant.

        Stamp the slot, clear any prior cancellation, and detect whether
        this booking is in fact a reschedule (a previously-archived event
        exists for the same invite — the native flow may cancel+rebook
        rather than move the original event in place).
        """
        self.ensure_one()
        vals = {
            'call_booked_start': event.start,
            'call_cancelled': False,
        }
        invite = event.appointment_invite_id
        if invite:
            had_previous = self.env['calendar.event'].sudo().with_context(
                active_test=False,
            ).search_count([
                ('appointment_invite_id', '=', invite.id),
                ('id', '!=', event.id),
            ])
            if had_previous:
                vals['call_rescheduled'] = True
        self.sudo().write(vals)
        self.invalidate_recordset(['meet_url', 'call_status'])

    def _call_meet_on_reschedule(self, event):
        """The booked event's start moved in place — mark as rescheduled."""
        self.ensure_one()
        self.sudo().write({
            'call_booked_start': event.start,
            'call_rescheduled': True,
            'call_cancelled': False,
        })
        self.invalidate_recordset(['meet_url', 'call_status'])

    def _call_meet_on_cancel(self, event):
        """The booked event was cancelled/archived — flag it and nudge the
        recruiter. We deliberately do NOT move the applicant off the Call
        Booked stage: candidate history stays visible in the kanban and the
        recruiter decides the next move. Reuses the call_stage recruiter
        alert helper (chatter note + To-Do activity).
        """
        self.ensure_one()
        self.sudo().write({'call_cancelled': True})
        self.invalidate_recordset(['meet_url', 'call_status'])
        self._call_stage_alert_recruiter(reason=_(
            "Call cancelled for applicant '%(name)s' (slot was %(slot)s). "
            "Decide: re-invite, refuse, or close.",
            name=self.display_name,
            slot=event.start or _('(unknown)'),
        ))
