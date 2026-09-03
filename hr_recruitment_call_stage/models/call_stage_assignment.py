# -*- coding: utf-8 -*-
"""Call Stage — the appointment type answers "who runs the call".

v17.0.25.0.0 gave the stage its own ``call_staff_user_ids`` ("Interviewer"),
narrowing the appointment type's staff per stage; v17.0.26.0.0 let it name
anyone by ADDING them to that type on save.

v17.0.28.0.0 removes it. "Who runs the call" was described in two places that
had to agree — the type's ``staff_user_ids`` and the stage's subset of it — and
they could not be kept in agreement. The subset is applied exactly once, when
the candidate's ``appointment.invite`` is minted, so anything that moves
afterwards silently degrades it into "anyone free": somebody edits the type's
staff, the picked person is archived, or the type is switched to schedule
resources. All three were reproduced on odoo_dev, and in the first the stage
form still stated "Every call from this stage goes to Ann" while it no longer
did.

Now the type is the only answer. Recruiters can already point a stage at a
COLLEAGUE's type — ``security/appointment_security.xml`` (v17.0.26.0.0) grants
read on every type, deliberately read-only — so nothing is lost by dropping the
subset, and one thing is gained: an invite that carries no staff filter makes
the booking page read the type's staff live on every request
(``appointment/controllers/appointment.py::_get_possible_staff_users``). Change
who is on the type and every link already in a candidate's inbox follows.

The trade accepted with the customer: two stages can no longer share one type
and route to different people. That needs two types, which is how six of the
seven types on this database were already set up.

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
# Sibling stages named in the pool-growth banner before it is summarised.
_MAX_SIBLINGS_SHOWN = 5


class HrJobStageConfig(models.Model):
    _inherit = 'hr.job.stage.config'

    # ------------------------------------------------------------------
    # Who runs the call
    # ------------------------------------------------------------------
    # v17.0.27.0.0 — `call_assign_mode` (This person / Anyone free / Applicant
    # picks) is GONE. It promised a choice the stage cannot make: whether the
    # candidate picks a person or Odoo auto-assigns one is
    # `appointment.type.assign_method`, which lives on the TYPE and which this
    # module never wrote. All three values produced identical invite payloads
    # once an interviewer was selected, so the control was decoration with one
    # side effect (a "one person only" constraint). What is real is surfaced
    # read-only instead.
    call_assign_hint = fields.Char(
        compute='_compute_call_assign_hint',
        string='How the interviewer is chosen')

    # The appointment type's current bookable staff. Since v17.0.26.0.0 this is
    # no longer the *domain* of the field below — it is the baseline we diff
    # the selection against to tell the recruiter who is about to be added.
    #
    # NOT a related field: `appointment.type` carries a record rule that limits
    # Appointment Users to their OWN types, so a plain related raises
    # AccessError the moment a recruiter opens a stage wired to a colleague's
    # type — and the dropdown silently comes back empty. Reading *which users
    # are bookable* is reference data, not sensitive, so the compute sudoes the
    # read. (The module ships a read-only ir.rule widening type visibility for
    # recruiters, but the sudo stays: it also covers non-recruiter callers.)
    call_staff_pool_ids = fields.Many2many(
        'res.users', string='Who runs the call',
        compute='_compute_call_staff_pool_ids',
        help="The appointment type's own bookable staff — the single answer to "
             "who takes a call booked from this stage. Edited on the "
             "appointment type, which is where the slot grid comes from too.")

    # ------------------------------------------------------------------
    # Shared-type warning
    # ------------------------------------------------------------------
    # Now that the stage keeps no subset of its own, picking a type IS the
    # whole configuration — so the one thing left worth flagging is that the
    # type is not exclusive to this stage. Changing its staff, its duration or
    # its questions changes those stages too, and the banner is what makes that
    # visible at the moment of choosing rather than a week later.
    call_pool_shared_stages = fields.Char(
        compute='_compute_call_shared_stages',
        string='Other stages using this appointment type')

    # ------------------------------------------------------------------
    # Warnings that the existing readiness panel does not cover
    # ------------------------------------------------------------------
    call_warn_staff_unsynced = fields.Boolean(
        compute='_compute_call_assignment_warnings',
        string='Interviewer has not connected Google Calendar')
    call_warn_unsynced_names = fields.Char(
        compute='_compute_call_assignment_warnings',
        string='Unsynced interviewers')
    call_warn_unsynced_breaks_meet = fields.Boolean(
        compute='_compute_call_assignment_warnings',
        string='Unsynced interviewer also costs the Meet link')
    call_warn_work_hours_off = fields.Boolean(
        compute='_compute_call_assignment_warnings',
        string='Working hours are not enforced')

    call_availability_7d = fields.Text(
        compute='_compute_call_availability_7d',
        string='Availability (next 7 days)',
        help="JSON payload for the availability preview widget. Recomputed "
             "whenever the appointment type or its staff changes; never "
             "stored.")

    # ------------------------------------------------------------------
    # Pool
    # ------------------------------------------------------------------
    @api.depends('booking_appointment_type_id',
                 'booking_appointment_type_id.staff_user_ids')
    def _compute_call_staff_pool_ids(self):
        for config in self:
            appt = config.booking_appointment_type_id
            config.call_staff_pool_ids = appt.sudo().staff_user_ids if appt else False

    @api.depends('is_call_stage', 'booking_appointment_type_id')
    def _compute_call_shared_stages(self):
        """Which other Call Stages book through the same appointment type.

        Before v17.0.28.0.0 this listed only siblings that had left their
        Interviewer empty, because those were the ones a pool growth could
        surprise. There is no pool growth and no Interviewer any more, so the
        answer is simply every other Call Stage on this type — all of them are
        affected by its staff, its duration and its questions alike.
        """
        Config = self.env['hr.job.stage.config'].sudo()
        for config in self:
            config.call_pool_shared_stages = False
            appt = config.booking_appointment_type_id
            if not config.is_call_stage or not appt:
                continue
            domain = [
                ('booking_appointment_type_id', '=', appt.id),
                ('is_call_stage', '=', True),
                ('id', '!=', config._origin.id or 0),
            ]
            # Capped: one type can back a dozen stages, and a banner nobody
            # finishes reading warns nobody.
            siblings = Config.search(domain, limit=_MAX_SIBLINGS_SHOWN)
            if not siblings:
                continue
            names = [
                '%s / %s' % (sibling.job_id.display_name or '-',
                             sibling.stage_id.display_name or '-')
                for sibling in siblings
            ]
            overflow = Config.search_count(domain) - len(siblings)
            if overflow > 0:
                names.append(_('and %s more', overflow))
            config.call_pool_shared_stages = ', '.join(names)

    def _call_appointment_type_sudo(self):
        """The stage's appointment type, readable regardless of its record rule.

        Every read below is display/derivation only. The single write this
        module performs on a type is the bridge forcing its videocall source.
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
        """Users whose calendars drive this stage's slots.

        Since v17.0.28.0.0 that is simply the appointment type's own staff:
        the stage no longer keeps a subset of it, so there is nothing here that
        can fall out of step with what the booking page actually offers.
        """
        self.ensure_one()
        appt = self._call_appointment_type_sudo()
        if not appt:
            return self.env['res.users']
        return appt.staff_user_ids

    # ------------------------------------------------------------------
    # How the interviewer is chosen — reported, not decided
    # ------------------------------------------------------------------
    @api.depends('is_call_stage', 'booking_appointment_type_id',
                 'booking_appointment_type_id.staff_user_ids',
                 'booking_appointment_type_id.assign_method')
    def _compute_call_assign_hint(self):
        """One sentence telling the recruiter what actually happens.

        The behaviour belongs to the appointment type (``assign_method``), and
        several stages can share one type — so the stage reports it instead of
        offering a control that would silently overwrite a sibling's setting.
        ``user_assign_method`` is the stock read of the same value for
        user-scheduled types ('time_resource' is not supported there and maps
        back to 'resource_time' — appointment_type.py:85).
        """
        for config in self:
            config.call_assign_hint = False
            appt = config._call_appointment_type_sudo()
            if not config.is_call_stage or not appt:
                continue
            staff = config._call_effective_staff()
            if not staff:
                continue
            if len(staff) == 1:
                config.call_assign_hint = _(
                    "Every call from this stage goes to %s.", staff.name)
                continue
            method = appt.user_assign_method or appt.assign_method
            if method == 'resource_time':
                config.call_assign_hint = _(
                    "The candidate picks one of the %s, then a free slot of "
                    "theirs.", len(staff))
            else:
                config.call_assign_hint = _(
                    "The candidate picks any slot at least one of the %s is "
                    "free for, and Odoo assigns that person.", len(staff))

    # ------------------------------------------------------------------
    # Warnings
    # ------------------------------------------------------------------
    @api.depends('is_call_stage', 'booking_appointment_type_id',
                 'booking_appointment_type_id.staff_user_ids',
                 'booking_appointment_type_id.work_hours_activated',
                 'booking_appointment_type_id.event_videocall_source')
    def _compute_call_assignment_warnings(self):
        for config in self:
            config.call_warn_staff_unsynced = False
            config.call_warn_unsynced_names = False
            config.call_warn_unsynced_breaks_meet = False
            config.call_warn_work_hours_off = False
            appt = config._call_appointment_type_sudo()
            if not config.is_call_stage or not appt:
                continue

            # v17.0.26.1.0 — this used to fire only for google_meet types, which
            # missed the bigger failure. Slot availability is computed from
            # `calendar.event` rows in Odoo alone
            # (appointment_type._slot_availability_prepare_users_values_meetings)
            # — the slot engine never calls Google. An interviewer who has not
            # connected their calendar therefore has NO busy time in Odoo, so
            # every slot looks free and the candidate can book straight over a
            # real meeting. That is true whatever the videocall source is.
            #
            # On a google_meet type it costs the join link as well: the link is
            # minted BY Google during _google_insert and written back post-sync
            # (appointment_google_calendar/models/calendar_event.py:41,53), so
            # an unsynced organiser means an invite with no way to join — and
            # the booking still succeeds, silently.
            unsynced = config._call_effective_staff().filtered(
                lambda u: not config._call_user_calendar_synced(u))
            if unsynced:
                config.call_warn_staff_unsynced = True
                config.call_warn_unsynced_names = ', '.join(
                    unsynced.mapped('name'))
                config.call_warn_unsynced_breaks_meet = (
                    appt.event_videocall_source == 'google_meet')

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
                 'booking_appointment_type_id.slot_ids')
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
