# -*- coding: utf-8 -*-
"""Call Stage — who runs the call, and a live 7-day availability preview.

v17.0.25.0.0 — implements design variant C (see
``obsidian/Projects/Call-Stage-Settings-Redesign/00-Design-Plan.md``):

* the **appointment type owns the pool** (``staff_user_ids``) — unchanged, and
  still the single source of bookable staff;
* the **stage config picks a subset of that pool** (``call_staff_user_ids``),
  which is carried onto the per-candidate ``appointment.invite``.

Why a subset and not a free-form user field: ``appointment.invite.staff_user_ids``
carries ``domain="[('id', 'in', suggested_staff_user_ids)]"`` where
``suggested_staff_user_ids`` is ``related='appointment_type_ids.staff_user_ids'``
(appointment/models/appointment_invite.py:41-54). **The invite can only narrow
the type's pool, never extend it.** Writing a user who is not in the pool is
silently dropped by the domain, so we mirror the same domain here and refuse it
loudly instead.

Deliberately NOT re-introduced: the v17.0.24.0.0-removed
``_sync_recruiter_staff_users`` UNION that auto-added recruiters to the
appointment type. Adding someone to the pool stays an explicit act on the
Appointment Type form; this module only ever selects from it.

Kept in its own file because ``hr_job_stage_config.py`` is already ~870 lines.
"""

import json
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Slot counts at or below this are shown amber ("few") rather than green.
_FEW_SLOTS = 2
_PREVIEW_DAYS = 7


class HrJobStageConfig(models.Model):
    _inherit = 'hr.job.stage.config'

    # ------------------------------------------------------------------
    # Who runs the call
    # ------------------------------------------------------------------
    call_assign_mode = fields.Selection(
        [('this_person', 'This person'),
         ('anyone_free', 'Anyone free'),
         ('applicant_picks', 'Applicant picks')],
        string='Who runs the call', default='this_person',
        help="How the interviewer is chosen for calls booked from this stage.\n"
             "• This person — one named interviewer.\n"
             "• Anyone free — Odoo auto-assigns whoever in the selection is free.\n"
             "• Applicant picks — the candidate chooses on the booking page.")

    # The pool, used ONLY as the domain source for the selection below. Never
    # written from here.
    #
    # NOT a related field: `appointment.type` carries a record rule that limits
    # recruiters to their OWN types, so a plain related raises AccessError the
    # moment a recruiter opens a stage wired to a colleague's type — and the
    # interviewer dropdown silently comes back empty. Reading *which users are
    # bookable* is reference data, not sensitive, so the compute sudoes the
    # read. Writing to the pool is still impossible from here.
    call_staff_pool_ids = fields.Many2many(
        'res.users', string='Bookable staff (pool)',
        compute='_compute_call_staff_pool_ids')

    call_staff_user_ids = fields.Many2many(
        'res.users', 'hr_job_stage_config_call_staff_user_rel',
        'config_id', 'user_id',
        string='Interviewer',
        domain="[('id', 'in', call_staff_pool_ids)]",
        help="Who runs calls booked from this stage. Must be part of the "
             "appointment type's bookable staff — add them there first if they "
             "are missing. Leave empty to use the whole pool.")

    # ------------------------------------------------------------------
    # Warnings that the existing readiness panel does not cover
    # ------------------------------------------------------------------
    call_warn_staff_unsynced = fields.Boolean(
        compute='_compute_call_assignment_warnings',
        string='Interviewer has not connected Google Calendar')
    call_warn_unsynced_names = fields.Char(
        compute='_compute_call_assignment_warnings',
        string='Unsynced interviewers')
    call_warn_work_hours_off = fields.Boolean(
        compute='_compute_call_assignment_warnings',
        string='Working hours are not enforced')

    call_availability_7d = fields.Text(
        compute='_compute_call_availability_7d',
        string='Availability (next 7 days)',
        help="JSON payload for the availability preview widget. Recomputed "
             "whenever the appointment type or the interviewer selection "
             "changes; never stored.")

    # ------------------------------------------------------------------
    # Pool
    # ------------------------------------------------------------------
    @api.depends('booking_appointment_type_id',
                 'booking_appointment_type_id.staff_user_ids')
    def _compute_call_staff_pool_ids(self):
        for config in self:
            appt = config.booking_appointment_type_id
            config.call_staff_pool_ids = appt.sudo().staff_user_ids if appt else False

    def _call_appointment_type_sudo(self):
        """The stage's appointment type, readable regardless of its record rule.

        Every read below is display/derivation only — never a write.
        """
        self.ensure_one()
        appt = self.booking_appointment_type_id
        return appt.sudo() if appt else appt

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _call_user_calendar_synced(self, user):
        """Whether ``user`` has a working Google Calendar connection.

        ``res.users.is_google_calendar_synced`` ships with ``google_calendar``,
        which this module does NOT depend on — the Meet/sync warnings are a
        bonus where that module happens to be installed, not a requirement.
        Without it we report "synced" so the preview is not gratuitously
        downgraded on a database that never had Google in the first place.
        """
        if not hasattr(user, 'is_google_calendar_synced'):
            return True
        return bool(user.is_google_calendar_synced())

    def _call_effective_staff(self):
        """Users whose calendars actually drive this stage's slots.

        The explicit selection when set, the whole pool otherwise — mirroring
        what ``appointment.invite`` does when ``staff_user_ids`` is empty.
        """
        self.ensure_one()
        appt = self._call_appointment_type_sudo()
        if not appt:
            return self.env['res.users']
        return self.call_staff_user_ids or appt.staff_user_ids

    def _call_invite_values(self):
        """Values to carry onto the per-candidate ``appointment.invite``.

        ``resources_choice`` is stock (appointment/models/appointment_invite.py:45):
        ``specific_resources`` pins named users, ``all_assigned_resources``
        leaves the whole pool bookable. Whether the candidate then *picks* a
        person or gets auto-assigned is the appointment type's
        ``user_assign_method`` — not something the invite decides.
        """
        self.ensure_one()
        staff = self._call_effective_staff()
        if not staff:
            return {}
        if self.call_assign_mode == 'this_person':
            return {
                'resources_choice': 'specific_resources',
                'staff_user_ids': [fields.Command.set(staff.ids)],
            }
        # anyone_free / applicant_picks: keep the selection bookable and let the
        # appointment type's assign method decide the front-end behaviour.
        if self.call_staff_user_ids:
            return {
                'resources_choice': 'specific_resources',
                'staff_user_ids': [fields.Command.set(staff.ids)],
            }
        return {'resources_choice': 'all_assigned_resources'}

    # ------------------------------------------------------------------
    # Guards — the pool is the boundary
    # ------------------------------------------------------------------
    @api.onchange('booking_appointment_type_id')
    def _onchange_booking_type_prune_staff(self):
        """Drop interviewers that the new appointment type does not offer.

        Without this the form silently keeps a stale selection that the domain
        rejects on save, and the recruiter gets a confusing error about a field
        they did not touch.
        """
        for config in self:
            pool = config._call_appointment_type_sudo().staff_user_ids
            if config.call_staff_user_ids:
                config.call_staff_user_ids = config.call_staff_user_ids & pool

    def write(self, vals):
        """Prune interviewers the incoming appointment type does not offer.

        The `@api.onchange` above only covers the form. On the ORM path
        (data import, API, multi-record write) the constraint would otherwise
        fire on a field the caller never touched, with an error naming a person
        they did not pick. Pruning here makes both paths behave the same; an
        EXPLICIT out-of-pool selection still raises, which is the point.
        """
        if 'booking_appointment_type_id' in vals and 'call_staff_user_ids' not in vals:
            appt = self.env['appointment.type'].sudo().browse(
                vals['booking_appointment_type_id'])
            pool = appt.staff_user_ids if appt else self.env['res.users']
            for config in self:
                stale = config.call_staff_user_ids - pool
                if stale:
                    config.call_staff_user_ids = [
                        fields.Command.unlink(u.id) for u in stale]
        return super().write(vals)

    @api.constrains('is_call_stage', 'call_staff_user_ids',
                    'booking_appointment_type_id')
    def _check_call_staff_within_pool(self):
        for config in self:
            if not config.is_call_stage or not config.call_staff_user_ids:
                continue
            pool = config._call_appointment_type_sudo().staff_user_ids
            outside = config.call_staff_user_ids - pool
            if outside:
                raise ValidationError(_(
                    "%(names)s cannot run calls booked from this stage: they "
                    "are not part of the bookable staff on appointment type "
                    "'%(appt)s'. Add them on the appointment type first, then "
                    "pick them here.",
                    names=', '.join(outside.mapped('name')),
                    appt=config.booking_appointment_type_id.display_name or '-',
                ))

    @api.constrains('is_call_stage', 'call_assign_mode', 'call_staff_user_ids')
    def _check_this_person_is_one_person(self):
        for config in self:
            if not config.is_call_stage or config.call_assign_mode != 'this_person':
                continue
            if len(config.call_staff_user_ids) > 1:
                raise ValidationError(_(
                    "'This person' means one interviewer, but %(count)s are "
                    "selected. Pick one, or switch to 'Anyone free' / "
                    "'Applicant picks'.",
                    count=len(config.call_staff_user_ids),
                ))

    # ------------------------------------------------------------------
    # Warnings
    # ------------------------------------------------------------------
    @api.depends('is_call_stage', 'booking_appointment_type_id',
                 'booking_appointment_type_id.staff_user_ids',
                 'booking_appointment_type_id.work_hours_activated',
                 'booking_appointment_type_id.event_videocall_source',
                 'call_staff_user_ids')
    def _compute_call_assignment_warnings(self):
        for config in self:
            config.call_warn_staff_unsynced = False
            config.call_warn_unsynced_names = False
            config.call_warn_work_hours_off = False
            appt = config._call_appointment_type_sudo()
            if not config.is_call_stage or not appt:
                continue

            # Google Meet links are minted BY Google during _google_insert and
            # written back post-sync (appointment_google_calendar/models/
            # calendar_event.py:41,53). An unsynced interviewer means the
            # candidate gets an invite with NO join link — and the booking
            # still succeeds, silently. Only worth warning about when the type
            # actually asks for a Meet link.
            if appt.event_videocall_source == 'google_meet':
                unsynced = config._call_effective_staff().filtered(
                    lambda u: not config._call_user_calendar_synced(u))
                if unsynced:
                    config.call_warn_staff_unsynced = True
                    config.call_warn_unsynced_names = ', '.join(
                        unsynced.mapped('name'))

            # Working hours are opt-in per appointment type
            # (appointment_hr/models/appointment_type.py:38 returns early when
            # work_hours_activated is False). With it off, the only thing
            # narrowing the slot grid is existing calendar.event busy time.
            config.call_warn_work_hours_off = not appt.work_hours_activated

    # ------------------------------------------------------------------
    # 7-day availability preview
    # ------------------------------------------------------------------
    @api.depends('is_call_stage', 'booking_appointment_type_id',
                 'booking_appointment_type_id.staff_user_ids',
                 'booking_appointment_type_id.slot_ids',
                 'call_staff_user_ids')
    def _compute_call_availability_7d(self):
        """Build the preview payload from the REAL slot engine.

        Uses ``appointment.type._get_appointment_slots(tz, filter_users=...)``
        — the very method the public booking page calls — so the grid can never
        disagree with what the candidate sees.
        """
        for config in self:
            config.call_availability_7d = False
            appt = config._call_appointment_type_sudo()
            if not config.is_call_stage or not appt:
                continue
            staff = config._call_effective_staff()
            payload = {
                'timezone': appt.appointment_tz or self.env.user.tz or 'UTC',
                'staff_count': len(staff),
                'trusted': True,
                'days': [],
            }
            if not staff:
                payload['error'] = 'no_staff'
                config.call_availability_7d = json.dumps(payload)
                continue

            # A slot count is only trustworthy if every interviewer's calendar
            # is actually synced; otherwise busy time may be missing entirely.
            payload['trusted'] = all(
                config._call_user_calendar_synced(u) for u in staff)

            try:
                counts = config._call_slot_counts_by_day(appt, staff)
            except Exception:  # pragma: no cover - defensive, never blocks the form
                _logger.warning(
                    "Call Stage availability preview failed for config %s",
                    config.id, exc_info=True)
                payload['error'] = 'compute_failed'
                config.call_availability_7d = json.dumps(payload)
                continue

            today = fields.Date.context_today(config)
            lead_days = int((appt.min_schedule_hours or 0) // 24)
            open_weekdays = {
                s.weekday for s in appt.slot_ids
                if s.slot_type == 'recurring' and s.weekday
            }
            horizon = appt.max_schedule_days or 0

            for offset in range(_PREVIEW_DAYS):
                day = today + timedelta(days=offset)
                count = counts.get(day, 0)
                payload['days'].append({
                    'date': day.isoformat(),
                    'weekday': day.strftime('%a'),
                    'daynum': day.day,
                    'count': count,
                    'level': config._call_slot_level(count),
                    'reason': config._call_empty_reason(
                        count, day, offset, open_weekdays, lead_days, horizon),
                })
            config.call_availability_7d = json.dumps(payload)

    def _call_slot_counts_by_day(self, appt, staff):
        """{date: free slot count} for the preview window."""
        self.ensure_one()
        tz = appt.appointment_tz or self.env.user.tz or 'UTC'
        slots_data = appt._get_appointment_slots(tz, filter_users=staff)
        today = fields.Date.context_today(self)
        cutoff = today + timedelta(days=_PREVIEW_DAYS)
        counts = {}
        for month in slots_data:
            for week in month.get('weeks', []):
                for day in week:
                    day_date = day.get('day')
                    if day_date and today <= day_date < cutoff:
                        counts[day_date] = len(day.get('slots') or [])
        return counts

    @api.model
    def _call_slot_level(self, count):
        if count <= 0:
            return 'none'
        if count <= _FEW_SLOTS:
            return 'few'
        return 'ok'

    @api.model
    def _call_empty_reason(self, count, day, offset, open_weekdays, lead_days,
                           horizon):
        """Why a day is empty — so the recruiter is not left guessing."""
        if count:
            return False
        if offset < lead_days:
            return 'lead_time'
        if horizon and offset >= horizon:
            return 'beyond_horizon'
        if open_weekdays and str(day.isoweekday()) not in open_weekdays:
            return 'off'
        return 'busy'
