# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import booking_button

_logger = logging.getLogger(__name__)


_CALL_STATUS_SELECTION = [
    ('no_link', 'No link yet'),
    ('link_ready', 'Link ready'),
    ('sent', 'Invite sent'),
    ('booked', 'Slot booked'),
    ('attended', 'Attended'),
    ('no_show', 'No-show'),
]
_CALL_OUTCOME_SELECTION = [
    ('pending', 'Pending'),
    ('attended', 'Attended'),
    ('no_show', 'No-show'),
]
_MESSENGER_TYPE_SELECTION = [
    ('telegram', 'Telegram'),
    ('whatsapp', 'WhatsApp'),
]


class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    # ------------------------------------------------------------------
    # Call Scheduling cockpit (v17.0.3.0.0)
    # ------------------------------------------------------------------
    # Per-applicant view of the booking flow. `booking_url` is a live
    # field-readable URL so email templates can render
    # `object.booking_url` from any send entrypoint (manual or tracked).
    # `call_status` is recruiter-facing — derived from invite presence,
    # calendar events and the recruiter-set `call_outcome`.

    booking_url = fields.Char(
        string='Booking link',
        compute='_compute_booking_url',
        store=False,
        help='Live booking URL read from the Appointments-minted '
             'appointment.invite.book_url for the current Call Stage. '
             'Readable from email templates via `object.booking_url`. '
             'Empty until a booking invite is minted.')

    call_outcome = fields.Selection(
        _CALL_OUTCOME_SELECTION,
        string='Call outcome',
        default='pending',
        copy=False,
        help='Recruiter-set outcome after the call. Drives the terminal '
             'states of call_status (attended / no_show).')

    call_status = fields.Selection(
        _CALL_STATUS_SELECTION,
        string='Call status',
        compute='_compute_call_status',
        store=False,
        copy=False,
        help='Recruiter-facing status of the call flow. Computed from '
             'invite presence, calendar event, and call_outcome.')

    call_scheduling_visible = fields.Boolean(
        compute='_compute_call_scheduling_visible',
        help='True when the applicant is on a job/stage that has a Call '
             'Stage config — drives visibility of the Call Scheduling UI '
             'section. NOT stored; computed per recruiter view.')

    candidate_tz = fields.Char(
        string='Candidate timezone',
        compute='_compute_candidate_tz',
        help='Best-effort timezone for the candidate, taken from their '
             'partner record. Surfaced next to the booking link so the '
             'recruiter immediately sees the slot translation.')

    # ------------------------------------------------------------------
    # Messenger contact (v17.0.13.0.0)
    # ------------------------------------------------------------------
    # One messenger contact per candidate, captured around call booking.
    # A single value + a type selector (NOT two fields): the candidate has
    # exactly ONE of Telegram OR WhatsApp, never both. Plain writable fields
    # — no compute, no inverse — so a future "Genie" import can pre-fill them
    # with zero extra plumbing. `copy=False` mirrors call_outcome to avoid
    # carrying personal contact data onto duplicates.
    messenger_type = fields.Selection(
        _MESSENGER_TYPE_SELECTION,
        string='Messenger',
        copy=False,
        help='Which messenger the candidate uses for the call: Telegram or '
             'WhatsApp. Selects how messenger_value is interpreted — a '
             'Telegram username/handle vs. a WhatsApp phone number. May be '
             'pre-filled from Genie or captured on the public booking form.')

    messenger_value = fields.Char(
        string='Messenger contact',
        copy=False,
        help='The candidate messenger contact. For WhatsApp this is a phone '
             'number (international format recommended, e.g. +1234567890); '
             'for Telegram this is a username/handle (e.g. @candidate). '
             'Interpretation depends on messenger_type.')

    # ------------------------------------------------------------------
    # Additional interviewers (v17.0.16.0.0)
    # ------------------------------------------------------------------
    # Internal users (e.g. CEO) who join THIS candidate's call beside the
    # recruiter. Seeded from the Call Stage config's interviewer_user_ids when
    # the candidate enters the Call Stage (see _call_stage_seed_interviewers),
    # then freely editable by the recruiter on the card. This is the single
    # source of truth at booking time: calendar_event.create injects exactly
    # these users' partners as attendees, and the public booking page shows
    # exactly these users' photos. `copy=False` mirrors the other call fields.
    call_interviewer_user_ids = fields.Many2many(
        'res.users', 'hr_applicant_call_interviewer_user_rel',
        'applicant_id', 'user_id',
        string='Additional interviewers',
        domain="[('share', '=', False)]",
        copy=False,
        help='Internal users who will join this call in addition to the '
             'recruiter and candidate. They get the calendar invite (with the '
             'Google Meet link) and their photo is shown to the candidate on '
             'the booking page. Pre-filled from the Call Stage default when '
             'the candidate enters the stage; adjust freely per-candidate.')

    # ------------------------------------------------------------------
    # Seed additional interviewers on Call Stage entry (v17.0.16.0.0)
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        # Seed interviewers for applicants BORN directly on a Call Stage
        # (e.g. when the Call Stage is the job's default/first stage, or an
        # import lands a candidate straight there) — the write-transition hook
        # below never fires for those. Seeding is empty-only, so this is a
        # no-op for applicants created elsewhere or with a pre-set list.
        records = super().create(vals_list)
        records._call_stage_seed_interviewers()
        return records

    def write(self, vals):
        # Seed only on an actual stage TRANSITION (old != new), captured
        # BEFORE super() runs. A same-value rewrite (stage_id set to the stage
        # the applicant already sits on) must NOT reseed — otherwise a
        # recruiter's deliberate clear would be silently undone by any later
        # save that happens to carry stage_id.
        seed_candidates = self.env['hr.applicant']
        if 'stage_id' in vals:
            new_stage_id = vals['stage_id']
            seed_candidates = self.filtered(
                lambda a: a.stage_id.id != new_stage_id)
        # Capture the pre-write interviewer set so we can reconcile already
        # booked (future) calendar events when the list changes — whether the
        # change comes from a recruiter editing the card or from the Call Stage
        # config delta-propagation. Captured only when the field is touched.
        old_interviewers = {}
        if 'call_interviewer_user_ids' in vals:
            old_interviewers = {
                applicant.id: applicant.call_interviewer_user_ids
                for applicant in self
            }
        res = super().write(vals)
        if seed_candidates:
            seed_candidates._call_stage_seed_interviewers()
        for applicant in self:
            if applicant.id not in old_interviewers:
                continue
            removed = old_interviewers[applicant.id] - applicant.call_interviewer_user_ids
            applicant._call_stage_sync_event_interviewers(removed)
        return res

    def _call_stage_sync_event_interviewers(self, removed_users):
        """Reconcile the applicant's FUTURE booked call events' attendees with
        the current ``call_interviewer_user_ids``.

        Only upcoming events are touched — a past call's attendee history is
        left intact. Both additions (newly-listed interviewers) and removals
        (``removed_users``) are pushed onto each event, which in turn syncs the
        attendee change to Google Calendar.
        """
        self.ensure_one()
        events = self.env['calendar.event'].sudo().search([
            ('applicant_id', '=', self.id),
            ('start', '>=', fields.Datetime.now()),
        ])
        for event in events:
            event._call_stage_reconcile_interviewers(removed_users)

    def _call_stage_seed_interviewers(self):
        """Pre-fill ``call_interviewer_user_ids`` from the Call Stage config's
        default ``interviewer_user_ids`` when a candidate enters that stage.

        Seeds only when:

        * the applicant's CURRENT stage is itself a Call Stage (exact match —
          not the fallback "any call stage on the job"), so a candidate sitting
          on an earlier stage is not pre-seeded prematurely; and
        * the applicant has no interviewers set yet — once seeded (or once the
          recruiter has curated the list, including clearing it) we never
          stomp their choice. This makes the field the predictable single
          source of truth used at booking time.
        """
        Config = self.env['hr.job.stage.config'].sudo()
        for applicant in self:
            if applicant.call_interviewer_user_ids or not applicant.job_id:
                continue
            config = Config.search([
                ('job_id', '=', applicant.job_id.id),
                ('stage_id', '=', applicant.stage_id.id),
                ('is_call_stage', '=', True),
            ], limit=1)
            if config and config.interviewer_user_ids:
                applicant.call_interviewer_user_ids = [
                    (6, 0, config.interviewer_user_ids.ids)]

    @api.depends('partner_id', 'partner_id.tz')
    def _compute_candidate_tz(self):
        for applicant in self:
            applicant.candidate_tz = (
                applicant.partner_id.tz
                if applicant.partner_id else False
            ) or False

    @api.depends('job_id', 'stage_id')
    def _compute_call_scheduling_visible(self):
        Config = self.env['hr.job.stage.config'].sudo()
        for applicant in self:
            if not applicant.job_id:
                applicant.call_scheduling_visible = False
                continue
            # Visible if ANY stage of this job is a Call Stage — covers
            # both pre-link applicants on earlier stages and booked
            # applicants on the Call Booked stage.
            applicant.call_scheduling_visible = bool(Config.search_count([
                ('job_id', '=', applicant.job_id.id),
                ('is_call_stage', '=', True),
            ]))

    def _get_current_call_appt_type(self):
        """Resolve the appointment.type that *this* applicant should book
        against right now. Reads the Call Stage config for the
        applicant's CURRENT stage; falls back to any Call Stage config
        on the same job (for applicants already advanced to Call Booked).
        """
        self.ensure_one()
        if not self.job_id:
            return self.env['appointment.type']
        Config = self.env['hr.job.stage.config'].sudo()
        cfg = Config.search([
            ('job_id', '=', self.job_id.id),
            ('stage_id', '=', self.stage_id.id),
            ('is_call_stage', '=', True),
        ], limit=1)
        if not cfg:
            cfg = Config.search([
                ('job_id', '=', self.job_id.id),
                ('is_call_stage', '=', True),
            ], limit=1)
        return cfg.booking_appointment_type_id

    def _get_current_invite(self):
        """Return the appointment.invite for this applicant tied to the
        current call appointment type. Empty recordset if none.
        """
        self.ensure_one()
        appt_type = self._get_current_call_appt_type()
        if not appt_type:
            return self.env['appointment.invite']
        return self.env['appointment.invite'].sudo().search([
            ('applicant_id', '=', self.id),
            ('appointment_type_ids', 'in', appt_type.ids),
        ], limit=1)

    def _get_upcoming_booked_call_event(self, invite=None):
        """Return this applicant's nearest UPCOMING, non-cancelled call event.

        ``invite`` scopes the search to a single ``appointment.invite`` (the
        booking link the candidate is using); when omitted the applicant's
        current invite is resolved. Cancelled events are archived (see
        ``calendar.event.action_cancel_meeting`` → ``action_archive``), so the
        default ``active=True`` domain excludes them — which is exactly why a
        reschedule (cancel + rebook) lets the candidate fall through to a fresh
        slot pick. Empty recordset when nothing upcoming is booked.

        Used by the public controller to short-circuit a returning candidate to
        their existing booking's confirmation page instead of the slot picker.
        """
        self.ensure_one()
        if invite is None:
            invite = self._get_current_invite()
        if not invite:
            return self.env['calendar.event']
        return self.env['calendar.event'].sudo().search([
            ('appointment_invite_id', '=', invite.id),
            ('applicant_id', '=', self.id),
            ('start', '>=', fields.Datetime.now()),
        ], order='start asc', limit=1)

    def _get_current_call_config(self):
        """Return the hr.job.stage.config row driving this applicant's
        current Call Stage. Falls back to any Call Stage config on the
        same job for applicants already advanced to Call Booked. Empty
        recordset when no Call Stage exists for the job.
        """
        self.ensure_one()
        if not self.job_id:
            return self.env['hr.job.stage.config']
        Config = self.env['hr.job.stage.config'].sudo()
        cfg = Config.search([
            ('job_id', '=', self.job_id.id),
            ('stage_id', '=', self.stage_id.id),
            ('is_call_stage', '=', True),
        ], limit=1)
        if not cfg:
            cfg = Config.search([
                ('job_id', '=', self.job_id.id),
                ('is_call_stage', '=', True),
            ], limit=1)
        return cfg

    @api.depends('job_id', 'stage_id')
    def _compute_booking_url(self):
        # The Appointments-minted invite URL is the single source of the
        # booking link. The email template reads the same value via
        # object.booking_url, so every entry point (manual send, tracked
        # send, preview) renders the link a recruiter sees in the cockpit.
        for applicant in self:
            applicant.booking_url = (
                applicant._get_current_invite().book_url or False)

    @api.depends('job_id', 'stage_id', 'call_outcome')
    def _compute_call_status(self):
        """Derive cockpit status.

        Intentionally **not stored**: the status also depends on state the
        ORM cannot express in `@api.depends` — the existence of an
        ``appointment.invite`` (a separate model, no inverse o2m here), of a
        booking ``calendar.event``, and of the "sent" chatter marker. A
        stored field would only recompute when one of the declared depends
        (``stage_id`` etc.) changed, so minting/sending a link — which leaves
        ``stage_id`` untouched — would leave a stale ``no_link``/``link_ready``
        on disk. Computing on read keeps the cockpit honest, mirroring the
        sibling non-stored ``booking_url`` (which already resolves the same
        invite chain per read). The action buttons additionally
        ``invalidate_recordset`` so the value refreshes within the same RPC.
        """
        CalendarEvent = self.env['calendar.event'].sudo()
        for applicant in self:
            if applicant.call_outcome == 'attended':
                applicant.call_status = 'attended'
                continue
            if applicant.call_outcome == 'no_show':
                applicant.call_status = 'no_show'
                continue
            invite = applicant._get_current_invite()
            # The Appointments invite is the only source of a booking
            # link now. No invite ⇒ no link. `booked` additionally
            # requires the calendar event the Appointments flow produces.
            if not invite:
                applicant.call_status = 'no_link'
                continue
            event = CalendarEvent.search(
                [('applicant_id', '=', applicant.id),
                 ('appointment_invite_id', '=', invite.id)], limit=1)
            if event:
                applicant.call_status = 'booked'
                continue
            # Heuristic: if a message of subtype "Note" with the call
            # template's email_from or model exists, consider it sent.
            # Cheaper: check if the invite was last touched in the past
            # (mint vs send is tracked at email layer). For Etap 3 we
            # mark `sent` only when action_send_invite_email ran, via
            # the dedicated chatter tag below — fall back to `link_ready`.
            if applicant._has_call_invite_sent_marker():
                applicant.call_status = 'sent'
            else:
                applicant.call_status = 'link_ready'

    def _has_call_invite_sent_marker(self):
        """True if `action_send_invite_email` has been fired at least
        once for this applicant. We tag the chatter message with a
        subtype-less internal marker; cheaper than searching mail.mail.
        """
        self.ensure_one()
        return bool(self.env['mail.message'].sudo().search_count([
            ('res_id', '=', self.id),
            ('model', '=', 'hr.applicant'),
            ('body', 'ilike', 'call-invite-sent-marker'),
        ]))

    # ------------------------------------------------------------------
    # Action buttons (v17.0.3.0.0)
    # ------------------------------------------------------------------
    def action_generate_booking_link(self):
        """Mint the booking invite for this applicant if not already
        minted. Idempotent — re-clicking returns the existing URL.
        """
        for applicant in self:
            appt_type = applicant._get_current_call_appt_type()
            if not appt_type:
                raise UserError(_(
                    "No Call Stage is configured for job '%(job)s'. Open "
                    "the job's Stages and tick 'Is Call Stage' on a stage "
                    "with an Appointment Type before generating a link.",
                    job=applicant.job_id.display_name or _('(unset)'),
                ))
            applicant._get_or_create_booking_invite(appt_type)
        # Backstop seed: applicants already on a Call Stage before this
        # feature landed never went through the stage-entry write hook.
        self._call_stage_seed_interviewers()
        # Force recompute of derived fields so the UI updates immediately.
        self.invalidate_recordset(['booking_url', 'call_status'])
        return True

    def action_send_invite_email(self):
        """Send the configured call-invite template to the candidate.
        Idempotent on the invite itself (reuses existing) — but each
        click does send a fresh email; recruiters call this manually.
        """
        for applicant in self:
            appt_type = applicant._get_current_call_appt_type()
            if not appt_type:
                raise UserError(_(
                    "No Call Stage is configured for this applicant's "
                    "job."))
            invite = applicant._get_or_create_booking_invite(appt_type)
            if not invite or not invite.book_url:
                applicant._call_stage_alert_recruiter(reason=_(
                    "Failed to mint a booking link for applicant "
                    "'%(name)s'.",
                    name=applicant.display_name))
                continue
            if not applicant.booking_url:
                applicant._call_stage_alert_recruiter(reason=_(
                    "Booking link is empty for applicant '%(name)s' — "
                    "email NOT sent.",
                    name=applicant.display_name))
                continue
            template = applicant._resolve_call_invite_template()
            if not template:
                raise UserError(_(
                    "Stage '%(stage)s' has no email template assigned.",
                    stage=applicant.stage_id.display_name))
            # Send-time guard (shared with the tracked path): never send a
            # call-invite that renders without a real booking link.
            if not applicant._call_stage_booking_button_ok(
                    template, applicant.booking_url):
                applicant._call_stage_alert_recruiter(reason=_(
                    "The call-invite email did not render a Book-a-call "
                    "button (template '%(tmpl)s' may be missing "
                    "`object.booking_url`, or the link failed to resolve). "
                    "The email was NOT sent.",
                    tmpl=template.display_name,
                ))
                continue
            # Pass booking_url in context for legacy templates that
            # still read `ctx.get('booking_url')`. New body reads
            # `object.booking_url`, which honours the same priority
            # chain so both paths render the same URL.
            template.with_context(
                booking_url=applicant.booking_url,
            ).send_mail(applicant.id, force_send=False)
            # Sent-marker — picked up by _compute_call_status.
            applicant.message_post(body=_(
                "Call-invite email queued for %(email)s. "
                "<!-- call-invite-sent-marker -->",
                email=applicant.email_from or _('(no email)'),
            ))
            applicant.invalidate_recordset(['call_status'])
        return True

    def action_resend_invite_email(self):
        """Same as action_send_invite_email but explicit naming for the
        button label. Recruiters use this after fixing a typo on the
        applicant or extending the link.
        """
        return self.action_send_invite_email()

    def action_mark_attended(self):
        for applicant in self:
            applicant.call_outcome = 'attended'
            applicant.message_post(body=_("Call marked as attended."))
        return True

    def action_open_call_stage_config(self):
        """Etap 4 breadcrumb: open the hr.job.stage.config row that drives
        this applicant's Call Stage. Lets the recruiter jump from the
        applicant straight to "where is this configured?" without
        hunting through menus.
        """
        self.ensure_one()
        cfg = self.env['hr.job.stage.config'].sudo().search([
            ('job_id', '=', self.job_id.id),
            ('stage_id', '=', self.stage_id.id),
            ('is_call_stage', '=', True),
        ], limit=1)
        if not cfg:
            cfg = self.env['hr.job.stage.config'].sudo().search([
                ('job_id', '=', self.job_id.id),
                ('is_call_stage', '=', True),
            ], limit=1)
        if not cfg:
            raise UserError(_(
                "No Call Stage is configured for job '%(job)s'.",
                job=self.job_id.display_name or _('(unset)'),
            ))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Call Stage Configuration'),
            'res_model': 'hr.job.stage.config',
            'res_id': cfg.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_mark_no_show(self):
        """Mark applicant as no-show AND schedule a recruiter follow-up
        activity so it surfaces in their to-do list, not just chatter.
        """
        for applicant in self:
            applicant.call_outcome = 'no_show'
            applicant.message_post(body=_("Call marked as no-show."))
            try:
                applicant.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Follow up on no-show'),
                    note=_(
                        "Candidate did not show up for the scheduled "
                        "call. Decide: re-invite, refuse, or close."),
                    user_id=(applicant.user_id or self.env.user).id,
                )
            except Exception:
                _logger.exception(
                    "Failed to schedule no-show follow-up activity for "
                    "applicant id=%s", applicant.id,
                )
        return True

    def _resolve_call_invite_template(self):
        """Return the mail.template configured for the applicant's
        current Call Stage. Falls back to the shipped generic template
        if the stage's own config row has none — same fallback the
        foundation uses for `template_id` on the stage record.
        """
        self.ensure_one()
        cfg = self.env['hr.job.stage.config'].sudo().search([
            ('job_id', '=', self.job_id.id),
            ('stage_id', '=', self.stage_id.id),
            ('is_call_stage', '=', True),
        ], limit=1)
        if cfg and cfg.mail_template_id:
            return cfg.mail_template_id
        return self.env.ref(
            'hr_recruitment_call_stage.mail_template_call_invite_generic',
            raise_if_not_found=False,
        ) or self.env['mail.template']

    # ------------------------------------------------------------------
    # Booking invite lifecycle (v17.0.2.0.0)
    # ------------------------------------------------------------------
    # Etap 2: native swap. We no longer keep our own join model
    # (hr.applicant.booking.invite); instead we read/write directly on
    # `appointment.invite.applicant_id` provided by
    # `appointment_hr_recruitment`. Uniqueness per
    # (applicant, appointment_type) is preserved via search-then-create
    # rather than a SQL constraint — single recruiter-driven creation
    # path keeps races impossible in practice.
    def _get_or_create_booking_invite(self, appointment_type):
        """Return the appointment.invite bound to (self, appointment_type),
        creating it (and a partner if needed) on first call.
        """
        self.ensure_one()
        if not appointment_type:
            return self.env['appointment.invite']
        Invite = self.env['appointment.invite'].sudo()
        invite = Invite.search([
            ('applicant_id', '=', self.id),
            ('appointment_type_ids', 'in', appointment_type.ids),
        ], limit=1)
        if invite:
            return invite
        if not self.partner_id:
            self._ensure_partner_for_booking()
        return Invite.create({
            'applicant_id': self.id,
            'appointment_type_ids': [(6, 0, appointment_type.ids)],
        })

    def _ensure_partner_for_booking(self):
        """Minimal partner creation for applicants who arrived without one.

        Stock `hr.applicant.action_makeMeeting` does this too but goes
        through a wizard. Here we only need an addressable res.partner so
        calendar.event attendees and ICS recipients work — same logic,
        smaller surface.
        """
        self.ensure_one()
        if self.partner_id:
            return self.partner_id
        partner = self.env['res.partner'].sudo().create({
            'name': self.partner_name or self.name,
            'email': self.email_from or False,
            'phone': self.partner_phone or False,
            'mobile': self.partner_mobile or False,
        })
        self.sudo().partner_id = partner.id
        return partner

    # ------------------------------------------------------------------
    # _track_template — inject booking_url into the rendering context
    # ------------------------------------------------------------------
    def _track_template(self, changes):
        # The foundation's _track_template already returns the right
        # template (config.mail_template_id → stage.template_id). We only
        # need to enrich the context for Call Stages.
        res = super()._track_template(changes)
        if 'stage_id' not in res or not self:
            return res
        applicant = self[:1]
        if not applicant.exists():
            return res
        config = self.env['hr.job.stage.config'].sudo().search([
            ('job_id', '=', applicant.job_id.id),
            ('stage_id', '=', applicant.stage_id.id),
        ], limit=1)
        if not config or not config.is_call_stage:
            # The stage is not a (valid) Call Stage, so we cannot mint a
            # booking link. If the resolved template nonetheless renders a
            # Book-a-call button (the production bug: a call-invite template
            # left wired to a stage whose "Is Call Stage" was un-ticked), the
            # candidate would receive a button-less invite — suppress the send
            # and alert the recruiter instead. Plain stage emails (no booking
            # button) pass through untouched.
            template = res['stage_id'][0]
            if booking_button.template_has_booking_token(template.body_html or ''):
                _logger.warning(
                    "hr_recruitment_call_stage: stage '%s' (job id=%s) is "
                    "sending a call-invite template but is not configured as "
                    "a Call Stage — suppressing button-less email for "
                    "applicant id=%s.",
                    applicant.stage_id.display_name, applicant.job_id.id,
                    applicant.id,
                )
                applicant._call_stage_alert_recruiter(reason=_(
                    "Stage '%(stage)s' is sending the call-invite email but "
                    "is not configured as a Call Stage. Tick 'Is Call Stage' "
                    "and set an Appointment Type (or remove the call-invite "
                    "template from this stage). The button-less email was NOT "
                    "sent to the candidate.",
                    stage=applicant.stage_id.display_name,
                ))
                res.pop('stage_id', None)
            return res
        # The booking link always comes from an Appointments-minted
        # invite — mint it here so the tracked send renders the same
        # object.booking_url the cockpit shows.
        appt_type = config.booking_appointment_type_id
        if not appt_type:
            # The @api.constrains guard normally prevents this, but a
            # legacy row created before the constraint landed could still
            # exist. Etap 1: suppress send entirely and alert the recruiter
            # — the candidate must never receive a button-less call invite.
            _logger.warning(
                "hr_recruitment_call_stage: Call Stage config id=%s has no "
                "appointment_type — suppressing call-invite email.",
                config.id,
            )
            applicant._call_stage_alert_recruiter(reason=_(
                "Call Stage '%(stage)s' has no Appointment Type configured. "
                "The call-invite email was NOT sent to the candidate. Fix "
                "the stage configuration and re-trigger from the applicant.",
                stage=applicant.stage_id.display_name,
            ))
            res.pop('stage_id', None)
            return res
        try:
            invite = applicant._get_or_create_booking_invite(appt_type)
        except Exception:
            # Etap 1: previously we sent the email anyway with a "reply
            # manually" fallback paragraph — that was unprofessional to the
            # candidate. Now we suppress the send and schedule a recruiter
            # activity so the issue surfaces in their to-do list.
            _logger.exception(
                "hr_recruitment_call_stage: failed to mint booking invite "
                "for applicant id=%s appt_type=%s",
                applicant.id, appt_type.id,
            )
            applicant._call_stage_alert_recruiter(reason=_(
                "Could not generate a booking link for stage '%(stage)s' "
                "(appointment type: %(appt)s). The call-invite email was "
                "NOT sent to the candidate. Please verify the appointment "
                "type and re-trigger from the applicant.",
                stage=applicant.stage_id.display_name,
                appt=appt_type.display_name,
            ))
            res.pop('stage_id', None)
            return res
        if not invite or not invite.book_url:
            # Defensive: empty invite / URL — never send a button-less email.
            applicant._call_stage_alert_recruiter(reason=_(
                "Booking link is empty for stage '%(stage)s'. The "
                "call-invite email was NOT sent.",
                stage=applicant.stage_id.display_name,
            ))
            res.pop('stage_id', None)
            return res
        template, opts = res['stage_id']
        # Send-time guard: render the ACTUAL template against this applicant
        # and confirm a real booking link comes out. Catches a template that
        # was edited to drop the button, or any case where booking_url fails
        # to resolve at render time despite a minted invite. Never let a
        # button-less invite reach the candidate.
        if not applicant._call_stage_booking_button_ok(template, invite.book_url):
            _logger.warning(
                "hr_recruitment_call_stage: rendered call-invite for "
                "applicant id=%s produced no booking link (template id=%s) — "
                "suppressing send.", applicant.id, template.id,
            )
            applicant._call_stage_alert_recruiter(reason=_(
                "The call-invite email for stage '%(stage)s' did not render a "
                "Book-a-call button (the template may be missing "
                "`object.booking_url`, or the booking link failed to "
                "resolve). The email was NOT sent. Fix the template and "
                "re-trigger from the applicant.",
                stage=applicant.stage_id.display_name,
            ))
            res.pop('stage_id', None)
            return res
        # Keep the outgoing mail.mail record. The call-invite template (and
        # the role-specific copies recruiters duplicate from it) default to
        # auto_delete=True, which permanently removes the mail.mail right
        # after a successful send — so the candidate's call invite vanishes
        # from Settings > Technical > Emails even though it WAS delivered.
        # Force-keep it here so every Call Stage send stays auditable,
        # regardless of the chosen template's own auto_delete flag.
        opts = dict(opts, auto_delete=False)
        res['stage_id'] = (
            template.with_context(booking_url=invite.book_url),
            opts,
        )
        return res

    # ------------------------------------------------------------------
    # Send-time booking-button guard (v17.0.22.0.0)
    # ------------------------------------------------------------------
    # The permanent fix for "call-invite email sent without the Book-a-call
    # button". Static config checks can be bypassed (template edited later,
    # booking_url empty at runtime, stage sending a call template while not
    # marked as a Call Stage), so we render the ACTUAL template against the
    # applicant and assert a real booking link came out BEFORE letting the
    # send proceed. Shared by both send entrypoints (tracked + manual).
    def _call_stage_render_body(self, template, book_url):
        """Render ``template`` body_html against this applicant with the
        booking URL in context. Returns the rendered HTML string, or ''
        when rendering fails (treated as a failed guard → suppress send).
        """
        self.ensure_one()
        try:
            rendered = template.with_context(
                booking_url=book_url or False,
            )._render_field(
                'body_html', self.ids, compute_lang=False)
            return rendered.get(self.id, '') or ''
        except Exception:
            _logger.exception(
                "hr_recruitment_call_stage: failed to render template id=%s "
                "for applicant id=%s during send-time guard",
                template.id, self.id,
            )
            return ''

    def _call_stage_booking_button_ok(self, template, book_url):
        """True when rendering ``template`` for this applicant yields a real
        booking link. The single assertion that gates every call-invite send.
        """
        self.ensure_one()
        rendered = self._call_stage_render_body(template, book_url)
        return booking_button.rendered_has_booking_link(rendered, book_url)

    # ------------------------------------------------------------------
    # Recruiter alert helper (Etap 1)
    # ------------------------------------------------------------------
    def _call_stage_alert_recruiter(self, reason):
        """Post a chatter note AND schedule a mail.activity on the
        responsible recruiter so the missing booking link surfaces in
        their to-do list rather than vanishing into chatter scroll.

        Falls back to chatter-only if the activity model is not available
        (defensive; should never happen since hr.applicant inherits
        mail.activity.mixin).
        """
        self.ensure_one()
        self.message_post(body=reason)
        try:
            todo_xmlid = 'mail.mail_activity_data_todo'
            self.activity_schedule(
                todo_xmlid,
                summary=_('Fix Call Stage booking link'),
                note=reason,
                user_id=(self.user_id or self.env.user).id,
            )
        except Exception:
            _logger.exception(
                "hr_recruitment_call_stage: failed to schedule recruiter "
                "activity for applicant id=%s", self.id,
            )
