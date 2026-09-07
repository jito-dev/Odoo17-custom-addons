# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.http import request

_logger = logging.getLogger(__name__)

# How long to wait, after a booking is cancelled, before deciding that the
# candidate is not coming back. See `_call_cancel_grace_minutes`.
DEFAULT_CANCEL_GRACE_MINUTES = 15
CANCEL_GRACE_PARAM = 'hr_recruitment_call_stage.cancel_grace_minutes'


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
             'without opening the calendar event. After a cancellation it '
             'holds the slot the candidate gave up.')

    call_cancelled = fields.Boolean(
        string='Call cancelled',
        copy=False,
        help='Set when the booked call is cancelled (candidate via the '
             'public page, recruiter by archiving the event, or a deletion '
             'coming back from Google Calendar). Cleared automatically when '
             'a new slot is booked.')

    call_rescheduled = fields.Boolean(
        string='Call rescheduled',
        copy=False,
        help='Set when the booked call has been moved at least once. Drives '
             'the `rescheduled` call_status flavour; reset on a clean first '
             'booking.')

    # === CANCELLATION SETTLING (v17.0.2.0.0) === #
    # A reschedule and a cancellation are the SAME event in the database at
    # the moment they happen: the portal has no "move" action, so
    # `Cancel/Reschedule` archives the event and sends the candidate back to
    # the slot picker (appointment/controllers/calendar.py). The two only
    # become distinguishable once the candidate either does or does not book
    # again — 12 to 60 seconds later, on the bookings measured in production.
    #
    # So the alert is no longer raised on the cancel itself. The fields below
    # hold "a cancellation is pending a verdict", and the verdict is taken by
    # `_cron_call_stage_confirm_cancellations` after a grace window.

    call_cancel_at = fields.Datetime(
        string='Cancelled at',
        copy=False,
        help='When the pending cancellation was recorded. Drives the grace '
             'window; cleared once the cancellation has been settled, either '
             'way.')

    call_cancel_activity_id = fields.Many2one(
        'mail.activity',
        string='Cancellation to-do',
        ondelete='set null',
        copy=False,
        index='btree_not_null',
        help='The recruiter to-do raised for this cancellation, so a late '
             'rebooking can retract exactly that one instead of guessing by '
             'its title. Closing the activity by hand empties this field on '
             'its own.')

    call_cancel_source = fields.Selection(
        [('candidate', 'Candidate'),
         ('staff', 'Staff'),
         ('google', 'Google Calendar')],
        string='Cancelled by',
        copy=False,
        help='Where the cancellation came from. The person cannot be '
             'identified — Odoo archives the event as the organiser even '
             'when the candidate clicked — so the source is recorded '
             'instead.')

    call_cancel_stage_id = fields.Many2one(
        'hr.recruitment.stage',
        string='Stage at cancellation',
        ondelete='set null',
        copy=False,
        help="The applicant's stage when the call was cancelled. A later "
             "Call Stage means this cancellation is history and must not "
             "raise a to-do.")

    call_status = fields.Selection(
        selection_add=[
            ('rescheduled', 'Rescheduled'),
            ('cancelled', 'Cancelled'),
        ],
        # call_status is a non-stored computed field, so `ondelete` is never
        # exercised; it is declared because `selection_add` requires it.
        ondelete={'rescheduled': 'set null', 'cancelled': 'set null'},
    )

    @api.depends('job_id', 'stage_id', 'call_cancelled')
    def _compute_meet_url(self):
        for applicant in self:
            # Reuse the same robust booked-event resolution that drives
            # `call_status` (across all the job's Call Stage types, not the
            # current-config invite) so the Join link appears whenever the
            # cockpit shows 'booked'.
            event = applicant._get_booked_call_event()
            applicant.meet_url = (event.videocall_location or False) if event else False

    # Restate the parent's dependencies (overriding the compute replaces the
    # field's trigger set) and add the two lifecycle signals.
    @api.depends('job_id', 'stage_id', 'call_outcome',
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

        Stamp the slot, clear any prior cancellation, and set the reschedule
        flag from the LIVE ``call_cancelled`` signal — never from the invite's
        event history.

        A candidate-driven reschedule always goes cancel → rebook: the old
        slot is archived first (``_call_meet_on_cancel`` flips
        ``call_cancelled`` on) and the new event is created right after, so at
        this point ``call_cancelled`` is the precise "the candidate is
        replacing a slot they just gave up" signal. Deriving ``rescheduled``
        from it (instead of "any event ever existed for this invite") keeps a
        clean first booking on ``booked`` even when a stale/past/cancelled or
        Google-sync-duplicate event lingers on the reused per-applicant invite,
        or when the job carries several Call Stages. Writing the flag
        unconditionally (``bool(call_cancelled)``) also self-resets a stale
        ``True`` left by an earlier, fully-cancelled reschedule — honouring the
        field's "reset on a clean first booking" contract.

        v17.0.2.0.0: this is also where a cancellation is retracted. Inside the
        grace window there is nothing to retract — no to-do was raised yet —
        and the sweep simply finds the applicant out of its domain. Past the
        window the to-do exists and WAS correct when it was raised, so it is
        closed as done rather than deleted.
        """
        self.ensure_one()
        was_cancelled = bool(self.call_cancelled)
        previous_start = self.call_booked_start
        # Read before the write: closing the activity empties the field
        # through `ondelete='set null'`.
        activity = self.call_cancel_activity_id
        self.sudo().write({
            'call_booked_start': event.start,
            'call_cancelled': False,
            'call_rescheduled': was_cancelled,
            'call_cancel_at': False,
            'call_cancel_source': False,
            'call_cancel_stage_id': False,
        })
        self.invalidate_recordset(['meet_url', 'call_status'])

        if was_cancelled:
            if previous_start and previous_start == event.start:
                # Round the cancel/rebook loop and back onto the slot they
                # started from. Nothing actually moved.
                self.message_post(body=_(
                    "Candidate re-booked the same slot (%(slot)s).",
                    slot=event.start,
                ))
            else:
                self.message_post(body=_(
                    "Call rescheduled: %(old)s → %(new)s.",
                    old=previous_start or _('(unknown)'), new=event.start,
                ))
        if activity:
            activity.sudo().action_feedback(feedback=_(
                "Candidate booked a new slot (%(slot)s).", slot=event.start,
            ))
            self.message_post(body=_(
                "Candidate booked %(slot)s — the open cancellation to-do was "
                "closed.", slot=event.start,
            ))

    def _call_meet_on_reschedule(self, event):
        """The booked event's start moved in place — mark as rescheduled."""
        self.ensure_one()
        self.sudo().write({
            'call_booked_start': event.start,
            'call_rescheduled': True,
            'call_cancelled': False,
            'call_cancel_at': False,
        })
        self.invalidate_recordset(['meet_url', 'call_status'])

    def _call_meet_on_cancel(self, event):
        """The booked event was cancelled/archived.

        Records the STATE and the CHRONICLE immediately — both are simply
        true, the event really was archived — and defers the OBLIGATION.

        The three carry very different costs when they are wrong. A wrong
        state recomputes on the next read; a wrong chatter note scrolls away;
        a wrong `mail.activity` sits in a recruiter's to-do list until a human
        opens and closes it. Production bore that out: of the nine applicants
        that ever raised this alert, six had merely rescheduled, and every one
        of those to-dos had to be closed by hand.

        So the to-do is left to `_cron_call_stage_confirm_cancellations`,
        which asks one question once the grace window has passed: does this
        applicant have a live booked call right now?

        We deliberately do NOT move the applicant off the Call Booked stage:
        candidate history stays visible in the kanban and the recruiter
        decides the next move.
        """
        self.ensure_one()
        self.sudo().write({
            'call_cancelled': True,
            'call_cancel_at': fields.Datetime.now(),
            'call_cancel_source': self._call_cancel_source(),
            'call_cancel_stage_id': self.stage_id.id,
        })
        self.invalidate_recordset(['meet_url', 'call_status'])

        # Cheap up-front gate so tidying up a call that already happened, or
        # one belonging to a candidate who is out of the funnel, makes no noise
        # at all. The sweep re-checks anyway — the funnel can move during the
        # window — so this only decides whether to bother anyone now.
        skip = self._call_cancel_skip_reason(slot=event.start)
        if skip:
            _logger.info(
                "hr_recruitment_call_stage_google_meet: booking cancelled for "
                "applicant id=%s, raising nothing (%s).", self.id, skip,
            )
            self.sudo().call_cancel_at = False
            return

        self.message_post(body=self._call_cancel_pending_note(event.start))
        self._call_meet_schedule_cancel_check()

    # ------------------------------------------------------------------
    # Settling a cancellation
    # ------------------------------------------------------------------
    @api.model
    def _call_cancel_grace_minutes(self):
        """How long to wait before calling a cancellation final.

        The longest gap measured between a cancel and its rebooking in
        production was 60 seconds; the default gives that a fifteenfold
        margin while still surfacing a real cancellation within the hour.

        :return: The window in minutes, never below 1.
        :rtype: int
        """
        raw = self.env['ir.config_parameter'].sudo().get_param(
            CANCEL_GRACE_PARAM, DEFAULT_CANCEL_GRACE_MINUTES)
        try:
            minutes = int(raw)
        except (TypeError, ValueError):
            _logger.warning(
                "hr_recruitment_call_stage_google_meet: %s is not a number "
                "(%r); falling back to %s minutes.",
                CANCEL_GRACE_PARAM, raw, DEFAULT_CANCEL_GRACE_MINUTES)
            minutes = DEFAULT_CANCEL_GRACE_MINUTES
        return max(minutes, 1)

    def _call_cancel_source(self):
        """Where this cancellation came from.

        The *person* cannot be identified: ``action_cancel_meeting`` archives
        the event ``with_user(self.user_id or SUPERUSER_ID)``, so the acting
        user is the organiser even when the candidate clicked the button —
        which is exactly why the chatter used to name a colleague who had done
        nothing. The session user, on the other hand, is honest: a portal
        visitor is the public user whatever the archive later runs as.

        Note: `self.ensure_one()`

        :return: 'google', 'candidate' or 'staff'.
        :rtype: str
        """
        self.ensure_one()
        if self.env.context.get('call_stage_cancel_from_google'):
            return 'google'
        if request and request.env.user._is_public():
            return 'candidate'
        return 'staff'

    def _call_cancel_pending_note(self, slot):
        """The chatter line posted the moment a booking is cancelled.

        States what happened and that the outcome is not known yet. It asks
        for nothing: at this point nobody can tell a reschedule from a
        walk-out.

        Note: `self.ensure_one()`

        :param slot: The cancelled slot.
        :rtype: str
        """
        self.ensure_one()
        if self.call_cancel_source == 'google':
            return _(
                "The call booked for %(slot)s was deleted from Google "
                "Calendar. Waiting to see whether a new slot is booked.",
                slot=slot or _('(unknown)'))
        if self.call_cancel_source == 'staff':
            return _(
                "The %(slot)s call slot was released in Odoo. Waiting to see "
                "whether a new slot is booked.", slot=slot or _('(unknown)'))
        return _(
            "Candidate released their %(slot)s call slot. Waiting to see "
            "whether they book a new one.", slot=slot or _('(unknown)'))

    def _call_cancel_skip_reason(self, slot=None):
        """Why this cancellation needs no recruiter decision, if it needs none.

        Checked both when the cancellation is recorded and again when it is
        settled, because the funnel can move during the grace window: a
        recruiter can refuse the candidate, or move them onto the next Call
        Stage, in the fifteen minutes we are waiting.

        Note: `self.ensure_one()`

        :param slot: The cancelled slot; defaults to `call_booked_start`.
        :return: A short reason for the log, empty when a decision IS needed.
        :rtype: str
        """
        self.ensure_one()
        if not self.active:
            return 'applicant is archived'
        if self.refuse_reason_id:
            return 'applicant is refused'
        slot = slot or self.call_booked_start
        if slot and slot < fields.Datetime.now():
            # Tidying up a call whose time has passed. "Re-invite, refuse or
            # close" is meaningless for a slot that is already behind us.
            return 'the cancelled slot is in the past'
        if not self._call_cancel_stage_is_relevant():
            return 'the applicant is past the call stages'
        if (self.call_cancel_stage_id
                and self.stage_id != self.call_cancel_stage_id
                and self._is_on_call_stage()):
            # Moved onto a DIFFERENT Call Stage: that stage has its own invite
            # and its own booking. The cancelled one is history.
            return 'the applicant moved on to another call stage'
        return ''

    def _call_cancel_stage_is_relevant(self):
        """True while a booked call still matters for this applicant.

        That is either a Call Stage itself, or the stage the auto-advance
        moves them to once they book. Anything further along — Offer, Hired —
        means the call has served its purpose, and its cancellation is not a
        decision anybody needs to take.

        Note: `self.ensure_one()`

        :rtype: bool
        """
        self.ensure_one()
        if self._is_on_call_stage():
            return True
        if not self.job_id or not self.stage_id:
            return False
        return bool(self.env['hr.job.stage.config'].sudo().search_count([
            ('job_id', '=', self.job_id.id),
            ('is_call_stage', '=', True),
            ('call_booked_stage_id', '=', self.stage_id.id),
        ]))

    def _call_meet_schedule_cancel_check(self):
        """Ask the sweep to look at this applicant once the window is up.

        `ir.cron._trigger(at=...)` is Odoo's own one-shot scheduling — the
        same call the framework uses for its vacuum — so this needs no job
        queue. The trigger is an optimisation, not the mechanism: the cron
        also runs on its own interval and selects by state, so a lost trigger
        only delays the verdict to the next pass.

        Note: `self.ensure_one()`
        """
        self.ensure_one()
        cron = self.env.ref(
            'hr_recruitment_call_stage_google_meet.'
            'ir_cron_call_stage_confirm_cancellations',
            raise_if_not_found=False,
        )
        if not cron:
            _logger.warning(
                "hr_recruitment_call_stage_google_meet: the cancellation "
                "sweep cron is missing; applicant id=%s will only be settled "
                "once it is restored.", self.id)
            return
        at = fields.Datetime.now() + timedelta(
            minutes=self._call_cancel_grace_minutes())
        # sudo(): a public visitor cancelling their own booking cannot read
        # ir.cron, but asking the framework to run its own job is system work.
        cron.sudo()._trigger(at=at)

    @api.model
    def _cron_call_stage_confirm_cancellations(self):
        """Settle every cancellation whose grace window has passed.

        This is a reconciliation over state, NOT a queue of pending
        notifications: the domain re-derives its work from the applicants
        themselves on every pass. A missed run, a night of downtime or a
        restore from backup therefore loses nothing — the next pass picks up
        whatever is still outstanding — and a double run is a no-op, because
        an applicant that already carries a to-do is out of the domain.

        (The queue-shaped version of this is what made the Google sync
        poison-pill unrecoverable: progress that lived only in a token a
        rollback could take back.)

        :return: True.
        :rtype: bool
        """
        cutoff = fields.Datetime.now() - timedelta(
            minutes=self._call_cancel_grace_minutes())
        applicants = self.search([
            ('call_cancelled', '=', True),
            ('call_cancel_at', '!=', False),
            ('call_cancel_at', '<=', cutoff),
            ('call_cancel_activity_id', '=', False),
        ])
        for applicant in applicants:
            # One applicant's failure must not roll the whole sweep back, or a
            # single bad row would block every other verdict for ever.
            try:
                with self.env.cr.savepoint():
                    applicant._call_meet_settle_cancellation()
            except Exception:
                _logger.exception(
                    "hr_recruitment_call_stage_google_meet: could not settle "
                    "the cancellation of applicant id=%s", applicant.id)
        return True

    def _call_meet_settle_cancellation(self):
        """Decide whether this cancellation needs a recruiter, and act.

        The whole question is: does the applicant have a live booked call
        right now? A reschedule leaves one behind (the old event archived, a
        new one active); a walk-out leaves nothing. Before the grace window
        both look identical, which is why this runs late rather than early.

        Note: `self.ensure_one()`

        :return: True when a to-do was raised.
        :rtype: bool
        """
        self.ensure_one()

        booked = self._get_booked_call_event()
        if booked:
            # A live booking: either the rebooking hook did not run (an event
            # un-archived by hand, a Google-side restore) or another call is
            # already in place. Either way this applicant is not cancelled.
            self.sudo().write({
                'call_cancelled': False,
                'call_cancel_at': False,
            })
            self.invalidate_recordset(['meet_url', 'call_status'])
            return False

        skip = self._call_cancel_skip_reason()
        if skip:
            _logger.info(
                "hr_recruitment_call_stage_google_meet: cancellation of "
                "applicant id=%s settled without a to-do (%s).", self.id, skip)
            # Keep `call_cancelled` — the call really was cancelled and the
            # cockpit must say so — but stop re-checking it.
            self.sudo().call_cancel_at = False
            return False

        activity = self._call_stage_alert_recruiter(
            reason=self._call_cancel_settled_note(),
            summary=_("Cancelled call — decide the next step"),
            date_deadline=self._call_cancel_deadline(),
        )
        self.sudo().write({
            'call_cancel_at': False,
            'call_cancel_activity_id': activity.id if activity else False,
        })
        return bool(activity)

    def _call_cancel_settled_note(self):
        """The chatter line posted once a cancellation is confirmed final.

        Note: `self.ensure_one()`

        :rtype: str
        """
        self.ensure_one()
        return _(
            "The %(slot)s call slot was released and no new booking arrived "
            "within %(minutes)s minutes. Decide: send the booking link again, "
            "refuse, or close.",
            slot=self.call_booked_start or _('(unknown)'),
            minutes=self._call_cancel_grace_minutes(),
        )

    def _call_cancel_deadline(self):
        """Today, or the next working day when today is a weekend.

        A cancellation settled one minute past midnight on a Saturday would
        otherwise land a to-do due on a day nobody is working, and it reads as
        already overdue by Monday morning.

        Note: `self.ensure_one()`

        :rtype: `datetime.date`
        """
        self.ensure_one()
        deadline = fields.Date.context_today(self)
        # Monday is 0, so 5 and 6 are Saturday and Sunday.
        if deadline.weekday() >= 5:
            deadline += timedelta(days=7 - deadline.weekday())
        return deadline
