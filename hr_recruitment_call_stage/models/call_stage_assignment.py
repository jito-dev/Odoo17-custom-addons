# -*- coding: utf-8 -*-
"""Call Stage — who runs the call, and a live 7-day availability preview.

v17.0.25.0.0 introduced design variant C (see
``obsidian/Projects/Call-Stage-Settings-Redesign/00-Design-Plan.md``): the
appointment type owned the pool and the stage config could only pick a
**subset** of it.

v17.0.26.0.0 amends that (see ``01-Interviewer-Assignment-Fix.md``). On real
data variant C degenerated exactly as its own "honest caveat" predicted: every
appointment type carried a single staff user — its creator — because
``appointment.type`` defaults ``staff_user_ids`` to ``self.env.user``
(appointment/models/appointment_type.py:33). A recruiter therefore found only
*themselves* in the Interviewer dropdown and could not hand the call to a
colleague at all.

The platform constraint has not changed and dictates the fix:
``appointment.invite.staff_user_ids`` carries
``domain="[('id', 'in', suggested_staff_user_ids)]"`` where
``suggested_staff_user_ids`` is ``related='appointment_type_ids.staff_user_ids'``
(appointment/models/appointment_invite.py:41-54). **The invite can only narrow
the type's pool, never extend it.** So "assign anyone" is only possible if the
person is put *into* the type's pool. That is now what happens:

* ``call_staff_user_ids`` accepts any internal user;
* the form warns, before saving, exactly who will be added to the type's
  bookable staff and which other stages share that type;
* on save the explicitly picked users are LINKED into
  ``appointment.type.staff_user_ids`` — union only, never an unlink.

Deliberately NOT re-introduced: the v17.0.24.0.0-removed
``_sync_recruiter_staff_users``, which pushed a whole separate
``recruiter_user_ids`` list into the type and removed people again when a
sibling config stopped naming them. Only the interviewers a human explicitly
picked here are ever added, and nobody is ever removed.

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
        'res.users', string='Bookable staff (pool)',
        compute='_compute_call_staff_pool_ids')

    call_staff_user_ids = fields.Many2many(
        'res.users', 'hr_job_stage_config_call_staff_user_rel',
        'config_id', 'user_id',
        string='Interviewer',
        domain="[('share', '=', False)]",
        help="Who runs calls booked from this stage. Anyone internal can be "
             "picked: on save they are added to the appointment type's "
             "bookable staff, so their calendar starts feeding the slot grid. "
             "Removing someone here never removes them from that pool. Leave "
             "empty to use the whole pool.")

    # ------------------------------------------------------------------
    # Pool-growth warning (v17.0.26.0.0) — shown BEFORE the save happens
    # ------------------------------------------------------------------
    call_pool_add_names = fields.Char(
        compute='_compute_call_pool_add_warning',
        string='Will be added to bookable staff')
    call_pool_shared_stages = fields.Char(
        compute='_compute_call_pool_add_warning',
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

    @api.depends('is_call_stage', 'call_staff_user_ids',
                 'booking_appointment_type_id',
                 'booking_appointment_type_id.staff_user_ids')
    def _compute_call_pool_add_warning(self):
        """Who this save would add to the type's pool, and who else it touches.

        Both are display-only: the banner exists so growing a *shared*
        appointment type is a visible, informed act rather than a silent side
        effect discovered later by whoever else books through that type.

        "Other stages" is deliberately limited to sibling Call Stages that left
        the Interviewer empty — those are the ones that book the whole pool and
        whose availability therefore changes. A sibling that names its own
        interviewers pins them on its invite and is unaffected.
        """
        Config = self.env['hr.job.stage.config'].sudo()
        for config in self:
            config.call_pool_add_names = False
            config.call_pool_shared_stages = False
            appt = config._call_appointment_type_sudo()
            if not config.is_call_stage or not appt:
                continue
            if appt.schedule_based_on != 'users':
                continue
            missing = config.call_staff_user_ids - appt.staff_user_ids
            if not missing:
                continue
            config.call_pool_add_names = ', '.join(missing.mapped('name'))
            sibling_domain = [
                ('booking_appointment_type_id', '=', appt.id),
                ('is_call_stage', '=', True),
                ('call_staff_user_ids', '=', False),
                ('id', '!=', config._origin.id or 0),
            ]
            # Capped: on real data one appointment type can back a dozen
            # stages, and a banner nobody finishes reading warns nobody.
            siblings = Config.search(sibling_domain, limit=_MAX_SIBLINGS_SHOWN)
            if siblings:
                names = [
                    '%s / %s' % (sibling.job_id.display_name or '-',
                                 sibling.stage_id.display_name or '-')
                    for sibling in siblings
                ]
                overflow = Config.search_count(sibling_domain) - len(siblings)
                if overflow > 0:
                    names.append(_('and %s more', overflow))
                config.call_pool_shared_stages = ', '.join(names)

    def _call_appointment_type_sudo(self):
        """The stage's appointment type, readable regardless of its record rule.

        Every read below is display/derivation only. The single write this
        module performs on a type goes through ``_call_grow_staff_pool``.
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
        ``assign_method`` — not something the invite decides, which is why
        v17.0.27.0.0 dropped the stage-level mode that pretended otherwise.

        The pinned users are guaranteed to be inside the type's pool because
        ``_call_grow_staff_pool`` put them there on save; the intersection
        below is a belt-and-braces guard for rows written before v17.0.26.0.0
        or mutated on the appointment type afterwards, so we never hand the
        invite a user its own domain would silently drop.
        """
        self.ensure_one()
        staff = self._call_effective_staff()
        if not staff:
            return {}
        if not self.call_staff_user_ids:
            # No explicit pick: the whole pool stays bookable.
            return {'resources_choice': 'all_assigned_resources'}
        appt = self._call_appointment_type_sudo()
        if appt:
            staff = staff & appt.staff_user_ids
            if not staff:
                return {}
        return {
            'resources_choice': 'specific_resources',
            'staff_user_ids': [fields.Command.set(staff.ids)],
        }

    # ------------------------------------------------------------------
    # Growing the pool — union only, never an unlink
    # ------------------------------------------------------------------
    def _call_grow_staff_pool(self):
        """Add the picked interviewers to the appointment type's bookable staff.

        Runs after ``super()`` in ``create``/``write`` so it sees the final
        selection. ``sudo()`` mirrors the policy already applied by
        ``_show_recruiter_avatar_on_booking_type``: a recruiter must not need
        write access on a colleague's appointment type to configure their own
        stage. The recruiter was told who would be added by the form banner
        before saving, and the addition is logged.

        Never unlinks: dropping an interviewer from this stage must not take
        their calendar away from every other stage booking through the type.
        """
        for config in self:
            if not config.is_call_stage or not config.call_staff_user_ids:
                continue
            appt = config._call_appointment_type_sudo()
            # Resource-based types have no staff at all, and `anytime` types are
            # capped at one user by a stock constraint — both are refused loudly
            # by _check_call_staff_assignable before we get here.
            if not appt or appt.schedule_based_on != 'users':
                continue
            missing = config.call_staff_user_ids - appt.staff_user_ids
            if not missing:
                continue
            appt.write({
                'staff_user_ids': [fields.Command.link(u.id) for u in missing],
            })
            _logger.info(
                "Call Stage %s (job %s / stage %s): user %s added %s to the "
                "bookable staff of appointment type %s",
                config.id, config.job_id.display_name,
                config.stage_id.display_name, self.env.user.login,
                ', '.join(missing.mapped('login')), appt.display_name)

    # ------------------------------------------------------------------
    # Guards — what the appointment type genuinely cannot host
    # ------------------------------------------------------------------
    @api.onchange('booking_appointment_type_id')
    def _onchange_booking_type_prune_staff(self):
        """Drop interviewers a resource-based type can never host.

        For a normal (user-based) type the selection is KEPT when the type
        changes — the missing people are simply added to the new type's pool on
        save, and the banner says so. Only a type that schedules resources
        instead of users has nowhere to put them, and silently keeping a
        selection there would surface later as an error about a field the
        recruiter never touched.
        """
        for config in self:
            appt = config._call_appointment_type_sudo()
            if appt and appt.schedule_based_on != 'users' and config.call_staff_user_ids:
                config.call_staff_user_ids = [fields.Command.clear()]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._call_grow_staff_pool()
        return records

    def write(self, vals):
        """Keep the type's pool in step with the interviewers picked here.

        The ORM path (data import, API, multi-record write) gets the same
        behaviour as the form: switching to a resource-based type prunes a
        selection it cannot host, and any other selection grows the new type's
        pool after the write lands.
        """
        if 'booking_appointment_type_id' in vals and 'call_staff_user_ids' not in vals:
            appt = self.env['appointment.type'].sudo().browse(
                vals['booking_appointment_type_id'])
            if appt and appt.schedule_based_on != 'users':
                for config in self:
                    if config.call_staff_user_ids:
                        config.call_staff_user_ids = [fields.Command.clear()]
        res = super().write(vals)
        if ('call_staff_user_ids' in vals
                or 'booking_appointment_type_id' in vals
                or 'is_call_stage' in vals):
            self._call_grow_staff_pool()
        return res

    @api.constrains('is_call_stage', 'call_staff_user_ids',
                    'booking_appointment_type_id')
    def _check_call_staff_assignable(self):
        """Refuse only what growing the pool cannot fix.

        Until v17.0.26.0.0 this constraint rejected ANY user outside the pool.
        That is now the normal case — the user gets added — and the check would
        fire from inside ``super().write()``, i.e. before ``_call_grow_staff_pool``
        ever runs. What remains are the two shapes of appointment type that
        genuinely cannot host an interviewer.
        """
        for config in self:
            if not config.is_call_stage or not config.call_staff_user_ids:
                continue
            appt = config._call_appointment_type_sudo()
            if not appt:
                continue
            if appt.schedule_based_on != 'users':
                raise ValidationError(_(
                    "Appointment type '%(appt)s' schedules resources, not "
                    "people, so it cannot have an interviewer. Pick a type "
                    "that schedules users, or clear the Interviewer field.",
                    appt=config.booking_appointment_type_id.display_name,
                ))
            # Stock constraint: an `anytime` type must have exactly one staff
            # user (appointment/models/appointment_type.py:327). Say so here,
            # rather than letting the pool growth fail with Odoo's own wording
            # about a record the recruiter never opened.
            if appt.category == 'anytime':
                combined = appt.staff_user_ids | config.call_staff_user_ids
                if len(combined) > 1:
                    raise ValidationError(_(
                        "Appointment type '%(appt)s' is an 'anytime' type, "
                        "which Odoo limits to a single bookable person "
                        "(currently %(current)s). Pick that person as the "
                        "interviewer, or use a regular appointment type.",
                        appt=config.booking_appointment_type_id.display_name,
                        current=', '.join(appt.staff_user_ids.mapped('name'))
                                or _('nobody'),
                    ))


    # ------------------------------------------------------------------
    # How the interviewer is chosen — reported, not decided
    # ------------------------------------------------------------------
    @api.depends('is_call_stage', 'call_staff_user_ids',
                 'booking_appointment_type_id',
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
                 'booking_appointment_type_id.event_videocall_source',
                 'call_staff_user_ids')
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
