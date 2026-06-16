# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from . import booking_button


_CALL_BOOKED_STAGE_XMLID = 'hr_recruitment_call_stage.stage_call_booked'
_CALL_INVITE_TEMPLATE_XMLID = (
    'hr_recruitment_call_stage.mail_template_call_invite_generic'
)


class HrJobStageConfig(models.Model):
    _inherit = 'hr.job.stage.config'

    is_call_stage = fields.Boolean(
        string='Is Call Stage',
        help='Tick to mark this stage as a call-scheduling stage. Recruiter '
             'then picks an Appointment Type; applicants moved here receive '
             'an email with a candidate-specific booking link, and are '
             'auto-advanced to the linked "Call Booked" stage upon '
             'confirmation.')

    booking_appointment_type_id = fields.Many2one(
        'appointment.type', string='Appointment Type',
        ondelete='set null',
        help='Odoo Appointments type used to mint the per-candidate booking '
             'URL injected into the assigned email template at render time.')

    call_booked_stage_id = fields.Many2one(
        'hr.recruitment.stage', string='Move to after booking',
        ondelete='set null',
        help='Stage the applicant is moved to once they confirm a slot. '
             'Auto-populated to the shipped "Call Booked" stage on first '
             'tick; editable for advanced setups.')

    # v17.0.6.0.0 — Etap 7: bind recruiter Odoo calendars to the booking pool.
    # When set, candidates booking through this Call Stage's appointment.type
    # see slots derived from these recruiters' internal Odoo calendars (the
    # native appointment.type.staff_user_ids mechanism). Sync semantics is
    # UNION across all configs sharing the same appointment.type — so two
    # stages that both reference appointment_type X with different recruiter
    # sets won't clobber each other.
    # v17.0.24.0.0 — HIDDEN & sync NEUTRALISED. The Appointment Type is now the
    # single source of truth for booking staff/calendars: set its
    # ``staff_user_ids`` directly on the appointment.type form, and its slots
    # flow to the Call Stage automatically. The field + column are kept (data
    # dormant, no migration) so the change is trivially reversible — un-hide it
    # in the views and restore ``_sync_recruiter_staff_users`` to re-enable.
    recruiter_user_ids = fields.Many2many(
        'res.users', 'hr_job_stage_config_recruiter_user_rel',
        'config_id', 'user_id',
        string='Booking calendars (internal staff)',
        domain="[('share', '=', False)]",
        help='DEPRECATED (v17.0.24.0.0): hidden; no longer feeds the booking '
             'pool. Configure booking staff on the Appointment Type instead. '
             'Internal Odoo users whose calendars feed the booking pool '
             'for this Call Stage. On save we add them to the appointment '
             "type's staff_user_ids (UNION — we never remove recruiters "
             'added by other Call Stage configs that share this '
             'appointment type). Leave empty to rely on whatever the '
             "appointment type's staff list already contains.")

    # v17.0.16.0.0 — additional interviewers (e.g. CEO, hiring manager) who
    # should JOIN the booked call alongside the recruiter and candidate, and
    # whose photo is shown to the candidate on the public booking page.
    #
    # Deliberately SEPARATE from recruiter_user_ids: these users are NOT added
    # to the appointment type's staff_user_ids, so they never gate slot
    # availability nor become bookable operators. They are only seeded onto an
    # applicant's call_interviewer_user_ids when the candidate enters this Call
    # Stage (recruiter can then override per-candidate), and from there injected
    # as calendar.event attendees at booking time.
    interviewer_user_ids = fields.Many2many(
        'res.users', 'hr_job_stage_config_interviewer_user_rel',
        'config_id', 'user_id',
        string='Additional interviewers',
        domain="[('share', '=', False)]",
        help='Internal users (e.g. CEO, hiring manager) added to the call as '
             'extra participants. They receive the calendar invite with the '
             'Google Meet link and their photo is shown to the candidate on '
             'the booking page. They do NOT affect slot availability. Seeded '
             'as the default interviewers on each candidate entering this Call '
             'Stage; the recruiter can adjust them per-candidate on the card.')

    # v17.0.17.0.0 — candidate-facing "What to expect" panel on the booking
    # page. Free text, one line per bullet: the controller splits it on
    # newlines (blank lines stripped) into a list the public template renders
    # as a bullet list in the right-hand meeting-details column. Purely
    # informational — never affects slot availability or the booking flow.
    what_to_expect = fields.Text(
        string='What to expect',
        help='Shown to the candidate on the booking page as a bullet list '
             '(one line = one bullet), e.g. "30-min technical discussion" / '
             '"Questions about your background". Leave empty to hide the panel.')

    # ------------------------------------------------------------------
    # Readiness panel (v17.0.23.0.0)
    # ------------------------------------------------------------------
    # Live, non-stored checks that drive the Call Stage Settings dialog so a
    # non-developer recruiter can tell at a glance whether the invite will go
    # out correctly. The hard save-gate is the @api.constrains above; these
    # fields only *surface* the state. The button-present check reuses the
    # same token detector as the constraint and the send-time guard, so the
    # panel never disagrees with what actually blocks/sends.
    call_check_template = fields.Boolean(
        compute='_compute_call_readiness', string='Email template selected')
    call_check_booking_button = fields.Boolean(
        compute='_compute_call_readiness', string='Booking button present')
    call_check_appointment = fields.Boolean(
        compute='_compute_call_readiness', string='Appointment type set')
    call_check_staff = fields.Boolean(
        compute='_compute_call_readiness',
        string='Booking calendar has staff')
    call_readiness_state = fields.Selection(
        [('ready', 'Ready to send'),
         ('needs_attention', 'Needs attention'),
         ('wont_send', "Won't send")],
        compute='_compute_call_readiness', string='Readiness')
    call_free_slot_count_7d = fields.Integer(
        compute='_compute_call_free_slot_count',
        string='Free slots (next 7 days)',
        help='Best-effort count of bookable slots in the next 7 days for the '
             'chosen Appointment Type. -1 means the count could not be '
             'computed (it never blocks sending).')

    def _call_stage_effective_template(self):
        """Template the send path will actually use for a Call Stage.

        MUST mirror ``hr.applicant._resolve_call_invite_template``: the
        per-job override (``mail_template_id``) first, then the *shipped
        call-invite* template — NOT the stage default ``template_id``.

        A Call Stage never sends ``stage_id.template_id`` (that is the
        generic recruitment template, e.g. "Application Acknowledgement",
        which has no Book-a-call button): on first tick the per-job
        override is auto-filled to the shipped call-invite. Resolving the
        stage default here made the @api.constrains save-guard reject a
        valid tick on stages that carry a default template (e.g. "New"),
        because it evaluated a template that would never actually be sent.
        Empty recordset only when the shipped template is missing
        (mid-install / uninstall).
        """
        self.ensure_one()
        if self.mail_template_id:
            return self.mail_template_id
        return self.env.ref(
            _CALL_INVITE_TEMPLATE_XMLID, raise_if_not_found=False
        ) or self.env['mail.template']

    @api.onchange('is_call_stage')
    def _onchange_is_call_stage_autofill_template(self):
        """v17.0.24.6.0 — live form feedback: the moment a recruiter ticks
        *This is a Call Stage*, pre-fill the shipped call-invite template in the
        form (before save), mirroring the create-wizard onchange. Only fills an
        EMPTY field — an explicit recruiter override is never stomped. The
        save-time `write()` auto-fill remains the backstop for non-onchange
        callers (API / multi-record writes).
        """
        if self.is_call_stage and not self.mail_template_id:
            default_template = self.env.ref(
                _CALL_INVITE_TEMPLATE_XMLID, raise_if_not_found=False)
            if default_template:
                self.mail_template_id = default_template

    @api.depends(
        'is_call_stage', 'mail_template_id', 'mail_template_id.body_html',
        'stage_id.template_id', 'stage_id.template_id.body_html',
        'booking_appointment_type_id',
        'booking_appointment_type_id.staff_user_ids')
    def _compute_call_readiness(self):
        for config in self:
            if not config.is_call_stage:
                config.call_check_template = False
                config.call_check_booking_button = False
                config.call_check_appointment = False
                config.call_check_staff = False
                config.call_readiness_state = False
                continue
            template = config._call_stage_effective_template()
            config.call_check_template = bool(template)
            config.call_check_booking_button = bool(
                template) and booking_button.template_has_booking_token(
                    template.body_html or '')
            appt = config.booking_appointment_type_id
            config.call_check_appointment = bool(appt)
            # NB: the "Move to after booking" (Call Booked) destination is
            # fully auto-managed and carries NO readiness check — it never
            # gates "won't send" and is not surfaced in the readiness panel.
            config.call_check_staff = bool(appt) and bool(appt.staff_user_ids)
            # Blocking checks decide "won't send"; the rest are warnings.
            blocking_ok = (
                config.call_check_booking_button
                and config.call_check_appointment
            )
            warnings_ok = config.call_check_staff
            if not blocking_ok:
                config.call_readiness_state = 'wont_send'
            elif not warnings_ok:
                config.call_readiness_state = 'needs_attention'
            else:
                config.call_readiness_state = 'ready'

    @api.depends(
        'is_call_stage', 'booking_appointment_type_id',
        'booking_appointment_type_id.staff_user_ids',
        'booking_appointment_type_id.slot_ids')
    def _compute_call_free_slot_count(self):
        # Best-effort and isolated in its own compute so the (potentially
        # heavy) slot generation only re-runs when the appointment type or
        # its staff/slots change — not on every keystroke in the dialog.
        from datetime import timedelta
        for config in self:
            appt = config.booking_appointment_type_id
            if not config.is_call_stage or not appt or not appt.staff_user_ids:
                config.call_free_slot_count_7d = -1
                continue
            try:
                tz = appt.appointment_tz or self.env.user.tz or 'UTC'
                slots_data = appt._get_appointment_slots(tz)
                today = fields.Date.context_today(config)
                cutoff = today + timedelta(days=7)
                count = 0
                for month in slots_data:
                    for week in month.get('weeks', []):
                        for day in week:
                            d = day.get('day')
                            if d and today <= d < cutoff:
                                count += len(day.get('slots') or [])
                config.call_free_slot_count_7d = count
            except Exception:
                # Never let a slot-generation hiccup break the config form.
                config.call_free_slot_count_7d = -1

    @api.constrains('is_call_stage', 'booking_appointment_type_id')
    def _check_call_stage_has_appointment_type(self):
        for config in self:
            if config.is_call_stage and not config.booking_appointment_type_id:
                raise ValidationError(_(
                    "Stage '%(stage)s' on job '%(job)s' is marked as a Call "
                    "Stage but has no Appointment Type. Pick one before "
                    "saving, otherwise the email button cannot render a "
                    "booking link.",
                    stage=config.stage_id.display_name,
                    job=config.job_id.display_name,
                ))

    @api.constrains('is_call_stage', 'mail_template_id', 'stage_id')
    def _check_call_stage_template(self):
        """Block saving a Call Stage whose email template would deliver a
        broken or button-less invite. Complements the appointment-type guard
        above and the foundation's template-model guard. The send-time guard
        in ``hr.applicant`` remains the runtime backstop for anything that
        slips past (e.g. the template edited after save).

        The template is validated only **when set**: enabling a Call Stage
        auto-fills the shipped template *after* the initial write, so this
        constraint must not reject the transient empty state. An *explicitly*
        assigned button-less template is still rejected here on the spot.

        NB: the "Move to after booking" (Call Booked) destination carries NO
        validation — it is fully auto-managed and never blocks saving.
        """
        for config in self:
            if not config.is_call_stage:
                continue
            stage_label = config.stage_id.display_name
            # Resolve the template exactly as the send path does:
            # per-job override first, then the shipped call-invite (NOT the
            # stage default — see _call_stage_effective_template). This keeps
            # the save-guard from rejecting a tick on a stage whose generic
            # default template (e.g. "Application Acknowledgement") has no
            # booking button but is never sent for a Call Stage.
            template = config._call_stage_effective_template()
            if template:
                if not template.model_id or template.model != 'hr.applicant':
                    raise ValidationError(_(
                        "The email template '%(tmpl)s' assigned to Call Stage "
                        "'%(stage)s' is not configured for applicants "
                        "(model = %(model)s). Pick a template whose Model is "
                        "'Applicant'.",
                        tmpl=template.display_name, stage=stage_label,
                        model=template.model or _('(not set)'),
                    ))
                if not booking_button.template_has_booking_token(
                        template.body_html or ''):
                    hint = booking_button.detect_near_miss(
                        template.body_html or '')
                    raise ValidationError(_(
                        "The email template '%(tmpl)s' assigned to Call Stage "
                        "'%(stage)s' has no Book-a-call button: its body does "
                        "not reference `object.booking_url`, so candidates "
                        "would get an email with no way to book.%(hint)s",
                        tmpl=template.display_name, stage=stage_label,
                        hint=(' ' + hint) if hint else '',
                    ))
            # NOTE: NO safeguard on the "Move to after booking" destination.
            # It is auto-managed (auto-paired on enable) and must never block
            # saving — per product decision, the Call Booked stage carries no
            # validation here.

    def write(self, vals):
        # Auto-manage the companion "Call Booked" stage exactly like
        # hr_recruitment_test_task._manage_test_task_stages does — but
        # per-(job, stage) rather than per-job.
        #
        # Detect first-time enablement BEFORE super() runs (otherwise
        # `self.is_call_stage` already reflects the new value).
        rows_enabling = self.browse()
        if vals.get('is_call_stage'):
            rows_enabling = self.filtered(lambda c: not c.is_call_stage)
        # Capture the pre-write interviewer defaults so a change can be
        # delta-propagated onto applicants currently on this Call Stage (and
        # their booked calendar events). Captured BEFORE super() runs.
        old_interviewers = {}
        if 'interviewer_user_ids' in vals:
            old_interviewers = {
                config.id: config.interviewer_user_ids for config in self
            }
        res = super().write(vals)
        if old_interviewers:
            for config in self:
                config._propagate_interviewer_defaults(
                    old_interviewers.get(config.id, self.env['res.users']))
        if rows_enabling:
            rows_enabling._sync_call_booked_membership()
            # v17.0.1.1.0: auto-fill the shipped call-invite template on rows
            # that have no per-job template yet. We skip ONLY when the same
            # write explicitly sets a TRUTHY template (recruiter picked one and
            # ticked is_call_stage in one save) — so it is preserved. A falsy
            # `mail_template_id` in vals (e.g. the web client sends
            # `mail_template_id: False` when the field is left empty) must NOT
            # suppress the fill, mirroring the create() guard (v17.0.24.6.0).
            # Untick path is a no-op by design — preserve any customised value.
            if not vals.get('mail_template_id'):
                rows_enabling._auto_fill_call_invite_template()
        # v17.0.6.0.0 — Etap 7: propagate recruiter_user_ids to the
        # appointment.type.staff_user_ids on EVERY write that touched any of
        # the three driving fields. We re-sync after super so the updated
        # values are visible on self.
        if (
            'recruiter_user_ids' in vals
            or 'booking_appointment_type_id' in vals
            or 'is_call_stage' in vals
        ):
            call_configs = self.filtered(
                lambda c: c.is_call_stage and c.booking_appointment_type_id
            )
            call_configs._sync_recruiter_staff_users()
            call_configs._show_recruiter_avatar_on_booking_type()
        return res

    def _propagate_interviewer_defaults(self, old_users):
        """Delta-propagate a change of ``interviewer_user_ids`` to the
        applicants this Call Stage currently governs.

        Behaviour (chosen design — DELTA, not full overwrite):

        * Only the *difference* is applied: users removed from the config are
          unlinked from each applicant's ``call_interviewer_user_ids``; users
          added are linked. A per-candidate interviewer the recruiter added by
          hand is therefore never stomped — only the changed users move.
        * Scope is this job's applicants sitting on the Call Stage itself or on
          its paired "Call Booked" stage (already-booked candidates), so the
          delta also reaches their future calendar events via the applicant
          write reconcile.

        The actual calendar-event attendee sync happens for free: writing
        ``call_interviewer_user_ids`` on the applicant triggers
        ``hr.applicant._call_stage_sync_event_interviewers``.
        """
        self.ensure_one()
        if not self.is_call_stage:
            return
        added = self.interviewer_user_ids - old_users
        removed = old_users - self.interviewer_user_ids
        if not added and not removed:
            return
        stages = self.stage_id
        if self.call_booked_stage_id:
            stages |= self.call_booked_stage_id
        if not stages or not self.job_id:
            return
        applicants = self.env['hr.applicant'].sudo().search([
            ('job_id', '=', self.job_id.id),
            ('stage_id', 'in', stages.ids),
        ])
        for applicant in applicants:
            current = applicant.call_interviewer_user_ids
            commands = []
            for user in removed:
                if user in current:
                    commands.append((3, user.id))
            for user in added:
                if user not in current:
                    commands.append((4, user.id))
            if commands:
                applicant.call_interviewer_user_ids = commands

    @api.ondelete(at_uninstall=False)
    def _archive_paired_call_booked_on_unlink(self):
        """v17.0.7.0.0 — Etap 8: when a Call Stage config row is removed,
        archive its paired Call Booked stage so the recruiter does not
        end up with orphan destination columns in the kanban.

        Behaviour:

        * Legacy global ``stage_call_booked`` is NEVER archived (it may
          still be referenced by old installs / external code).
        * A paired stage is archived only when no OTHER active Call
          Stage config row (outside the rows being unlinked) still
          references it. This handles the unlikely case where a
          recruiter manually pointed two Call Stages at the same
          custom destination.
        * Applicants currently on the paired stage are NOT moved or
          unlinked — recruiter sees them via the "Archived" kanban
          filter (consilium decision: don't lose candidate history).
        """
        self._archive_paired_call_booked(exclude_config_ids=self.ids)

    def _archive_paired_call_booked(self, exclude_config_ids=()):
        """Hide the paired Call Booked column from the kanban of every
        affected job by setting ``visible=False`` on its
        ``hr.job.stage.config`` row.

        Note: ``hr.recruitment.stage`` has no ``active`` field in Odoo 17
        (see odoo17_community/addons/hr_recruitment/models/hr_recruitment_stage.py),
        so the natural "archive" mechanism is the foundation's per-job
        ``visible`` flag — it removes the column from kanban via the
        applicant's ``allowed_stage_ids`` chain while leaving the stage
        record and any applicants on it intact. Recruiter can re-show
        the column via the Stages tab on the job.
        """
        legacy_global = self.env.ref(
            _CALL_BOOKED_STAGE_XMLID, raise_if_not_found=False)
        Config = self.env['hr.job.stage.config'].sudo()
        excluded = set(exclude_config_ids)
        for source_cfg in self:
            paired = source_cfg.call_booked_stage_id
            if not paired or (legacy_global and paired == legacy_global):
                continue
            other_refs = Config.search_count([
                ('call_booked_stage_id', '=', paired.id),
                ('is_call_stage', '=', True),
                ('id', 'not in', list(excluded)),
            ])
            if other_refs:
                continue
            paired_cfg = Config.search([
                ('job_id', '=', source_cfg.job_id.id),
                ('stage_id', '=', paired.id),
            ])
            paired_cfg.filtered('visible').write({'visible': False})

    @api.model_create_multi
    def create(self, vals_list):
        # Pre-super: for vals dicts that turn the row into a call stage
        # without specifying a template, inject the shipped default so the
        # row is born with a usable template (mirrors the write path).
        default_template = self.env.ref(
            _CALL_INVITE_TEMPLATE_XMLID, raise_if_not_found=False)
        if default_template:
            for vals in vals_list:
                if vals.get('is_call_stage') and not vals.get('mail_template_id'):
                    vals['mail_template_id'] = default_template.id
        records = super().create(vals_list)
        records.filtered('is_call_stage')._sync_call_booked_membership()
        call_configs = records.filtered(
            lambda c: c.is_call_stage and c.booking_appointment_type_id
        )
        call_configs._sync_recruiter_staff_users()
        call_configs._show_recruiter_avatar_on_booking_type()
        return records

    def action_preview_call_invite(self):
        """Etap 4: render the assigned call-invite template against a
        synthetic applicant so the recruiter sees exactly what the
        candidate would receive — including the booking button — before
        committing the stage config.

        Picks the first existing applicant on this (job, stage) as the
        sample; falls back to a transient ghost preview if none exist.
        """
        self.ensure_one()
        if not self.mail_template_id:
            raise UserError(_(
                "No email template assigned. Pick one on the Email page "
                "first."))
        Applicant = self.env['hr.applicant'].sudo()
        sample = Applicant.search([
            ('job_id', '=', self.job_id.id),
            ('stage_id', '=', self.stage_id.id),
        ], limit=1)
        sample_url = (
            'https://example.com/book/'
            'PREVIEW-NOT-A-REAL-LINK')
        if sample:
            actual = sample._get_current_invite()
            if actual and actual.book_url:
                sample_url = actual.book_url
        rendered_body = self.mail_template_id.with_context(
            booking_url=sample_url,
        )._render_field(
            'body_html', sample.ids if sample else [],
            compute_lang=False,
        ) if sample else {0: self.mail_template_id.body_html or ''}
        rendered_subject = self.mail_template_id.with_context(
            booking_url=sample_url,
        )._render_field(
            'subject', sample.ids if sample else [],
            compute_lang=False,
        ) if sample else {0: self.mail_template_id.subject or ''}
        body = next(iter(rendered_body.values()))
        subject = next(iter(rendered_subject.values()))
        # Open a transient wizard-like view with the rendered output.
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Email preview: %s', subject),
                'message': body,
                'sticky': True,
                'type': 'info',
            },
        }

    # ------------------------------------------------------------------
    # Call Stage Settings toolbar + status chips (v17.0.23.0.0)
    # ------------------------------------------------------------------
    def _call_stage_sample_applicant(self):
        """Pick a representative applicant to render previews / test emails
        against: one on this exact (job, stage) first, then any on the job.
        Empty recordset when the job has no applicants yet.
        """
        self.ensure_one()
        Applicant = self.env['hr.applicant'].sudo()
        sample = Applicant.search([
            ('job_id', '=', self.job_id.id),
            ('stage_id', '=', self.stage_id.id),
        ], limit=1)
        if not sample:
            sample = Applicant.search([('job_id', '=', self.job_id.id)], limit=1)
        return sample

    def action_preview_email(self):
        """Render the effective template against a sample applicant and open
        the OWL iframe preview dialog (styled, device toggle, highlighted
        booking button, red banner when the button is absent).
        """
        self.ensure_one()
        template = self._call_stage_effective_template()
        if not template:
            raise UserError(_(
                "No email template is assigned to this stage. Pick one on the "
                "Email page first."))
        sample = self._call_stage_sample_applicant()
        sample_url = 'https://example.com/book/PREVIEW-NOT-A-REAL-LINK'
        if sample:
            invite = sample._get_current_invite()
            if invite and invite.book_url:
                sample_url = invite.book_url
        ctx_template = template.with_context(booking_url=sample_url)
        if sample:
            body = ctx_template._render_field(
                'body_html', sample.ids, compute_lang=False)[sample.id]
            subject = ctx_template._render_field(
                'subject', sample.ids, compute_lang=False)[sample.id]
        else:
            body = template.body_html or ''
            subject = template.subject or ''
        # The banner reflects whether the TEMPLATE carries the button (a
        # static-correctness question); the send-time guard covers runtime URL
        # resolution separately.
        has_button = booking_button.template_has_booking_token(
            template.body_html or '')
        preview = self.env['hr.call.stage.preview'].create({
            'config_id': self.id,
            'subject': subject or '',
            'rendered_body': body or '',
            'booking_url': sample_url,
            'has_button': has_button,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Email preview'),
            'res_model': 'hr.call.stage.preview',
            'res_id': preview.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_send_test_email(self):
        """Send a [TEST]-prefixed copy of the call-invite to the current user
        so a recruiter can eyeball the real, styled email in their inbox.
        """
        self.ensure_one()
        template = self._call_stage_effective_template()
        if not template:
            raise UserError(_(
                "No email template is assigned to this stage."))
        sample = self._call_stage_sample_applicant()
        if not sample:
            raise UserError(_(
                "There is no candidate on this job to render a test against. "
                "Add a candidate, or use 'Preview rendered email' instead."))
        recipient = self.env.user.email or self.env.user.partner_id.email
        if not recipient:
            raise UserError(_(
                "Your user has no email address set, so the test cannot be "
                "delivered."))
        book_url = False
        if self.booking_appointment_type_id:
            invite = sample._get_or_create_booking_invite(
                self.booking_appointment_type_id)
            book_url = invite.book_url if invite else False
        ctx_template = template.with_context(booking_url=book_url)
        subject = ctx_template._render_field(
            'subject', sample.ids, compute_lang=False)[sample.id]
        ctx_template.send_mail(
            sample.id, force_send=True,
            email_values={
                'email_to': recipient,
                'subject': '[TEST] %s' % (subject or ''),
            })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Test email sent'),
                'message': _('A [TEST] copy was sent to %s.', recipient),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_open_booking_page(self):
        """Open the candidate-facing booking page in a new tab: a sample
        candidate's minted link when available, else the appointment type's
        public page.
        """
        self.ensure_one()
        url = False
        sample = self._call_stage_sample_applicant()
        if sample:
            invite = sample._get_current_invite()
            if invite and invite.book_url:
                url = invite.book_url
        if not url and self.booking_appointment_type_id:
            url = '/appointment/%s' % self.booking_appointment_type_id.id
        if not url:
            raise UserError(_(
                "No appointment type is set, so there is no booking page to "
                "open."))
        return {'type': 'ir.actions.act_url', 'url': url, 'target': 'new'}

    def _open_record_action(self, model, res_id, name):
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'res_id': res_id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_applicants(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Applicants'),
            'res_model': 'hr.applicant',
            'view_mode': 'tree,form',
            'domain': [
                ('job_id', '=', self.job_id.id),
                ('stage_id', '=', self.stage_id.id),
            ],
            'context': {'default_job_id': self.job_id.id},
        }

    def action_open_call_template(self):
        self.ensure_one()
        template = self._call_stage_effective_template()
        if not template:
            raise UserError(_("No email template is assigned to this stage."))
        return self._open_record_action(
            'mail.template', template.id, _('Email template'))

    def action_open_appointment_type(self):
        self.ensure_one()
        if not self.booking_appointment_type_id:
            raise UserError(_("No appointment type is set."))
        return self._open_record_action(
            'appointment.type', self.booking_appointment_type_id.id,
            _('Appointment type'))

    def _auto_fill_call_invite_template(self):
        """Fill `mail_template_id` with the shipped call-invite template on
        rows that have none. Idempotent: rows with any existing template are
        left untouched (preserve recruiter overrides). Graceful when the
        shipped template is missing (mid-install / uninstall).
        """
        default_template = self.env.ref(
            _CALL_INVITE_TEMPLATE_XMLID, raise_if_not_found=False)
        if not default_template:
            return
        rows_needing = self.filtered(lambda c: not c.mail_template_id)
        if rows_needing:
            rows_needing.write({'mail_template_id': default_template.id})

    def _sync_call_booked_membership(self):
        """v17.0.7.0.0 — Etap 8: ensure each config row has its OWN paired
        ``<call stage name> — Call Booked`` stage, scoped to the job.

        Replaces the previous "one global Call Booked attached to many
        jobs" design. Each Call Stage now owns a distinct destination
        stage so two Call Stages on the same job (e.g. Intro vs. Tech)
        do not collapse their booked candidates into a shared bucket.

        Reuse rule: if ``call_booked_stage_id`` is already set AND that
        stage is a per-config paired stage (specifically not the legacy
        global ``stage_call_booked``), the row is left alone — recruiters
        may rename their paired stage and the rename survives.

        Race-safe vs. the foundation's stage write override: paired
        stages are created with ``skip_inverse_scope=True`` so the
        scope-precompute inverse does not race the job_ids assignment.
        """
        Stage = self.env['hr.recruitment.stage'].sudo()
        legacy_global = self.env.ref(
            _CALL_BOOKED_STAGE_XMLID, raise_if_not_found=False)
        for config in self:
            already_paired = (
                config.call_booked_stage_id
                and config.call_booked_stage_id != legacy_global
            )
            if already_paired:
                continue
            call_stage = config.stage_id
            job = config.job_id
            if not call_stage or not job:
                continue
            paired = Stage.with_context(skip_inverse_scope=True).create({
                'name': _('%s — Call Booked', call_stage.name),
                'sequence': (call_stage.sequence or 0) + 1,
                'fold': False,
                'job_ids': [(6, 0, [job.id])],
                'default_visible_in_new_jobs': False,
            })
            # Foundation creates the (job, paired) config row with
            # visible=True via _ensure_config_rows_for_jobs; nothing more
            # to do for visibility. Stamp the back-reference.
            super(HrJobStageConfig, config).write({
                'call_booked_stage_id': paired.id,
            })

    def _sync_recruiter_staff_users(self):
        """DEPRECATED / NEUTRALISED (v17.0.24.0.0).

        The per-(job, stage) ``recruiter_user_ids`` ("Booking calendars")
        field is hidden and no longer drives the booking pool: the
        **Appointment Type is now the single source of truth** for booking
        staff/calendars (set ``staff_user_ids`` directly on the
        ``appointment.type`` form). This method is kept as a no-op so the
        existing call sites stay intact and the behaviour is trivially
        reversible (restore the body + un-hide the field). Existing
        ``recruiter_user_ids`` data is left dormant in the column — no
        migration, no data loss; it simply stops overriding the type.

        Historic behaviour (restore to re-enable) is preserved below as a
        docstring for reference:

        Semantics — **opt-in REPLACE with union across sibling configs**:

        * If NO sibling Call Stage config that targets this appointment
          type declares any ``recruiter_user_ids``, we do not touch
          ``staff_user_ids`` at all. This preserves the recruiter's
          "set the staff list directly on the appointment.type form"
          workflow — the Call Stage config simply abstains from
          managing the pool.

        * If AT LEAST ONE sibling config declares
          ``recruiter_user_ids`` for this appointment type, the
          appointment type becomes config-managed: ``staff_user_ids``
          is set to the UNION of ``recruiter_user_ids`` across every
          such sibling. Two stages sharing one appointment type with
          different pools cooperate via union; a recruiter is removed
          the moment no sibling config still names them. Manual
          additions on the appointment.type form do NOT survive this
          mode — once you opt in by setting ``recruiter_user_ids``,
          configs own the pool.

        Trade-off versus pure UNION-never-removes: a strict union
        would leave stale recruiters forever in the pool whenever a
        config un-names them, which is rarely what the recruiter
        meant. Trade-off versus per-config REPLACE: cross-config
        coordination through union avoids stages stomping each other
        when they share a type.
        """
        # NEUTRALISED: the Appointment Type owns its staff_user_ids directly.
        return

    def _show_recruiter_avatar_on_booking_type(self):
        """Enable staff pictures on the public booking page of each Call Stage's
        booking appointment type.

        The recruitment booking page swaps the appointment-type cover image for
        the assigned recruiter's photo (see the
        ``appointment_meeting_details`` override in appointment_templates.xml).
        That photo is served by the public ``/appointment/<id>/avatar`` route,
        which only returns a real picture when the type's ``avatars_display`` is
        'show' (otherwise a generic placeholder). Forcing it here means the
        recruiter never has to flip the "Show Pictures" option by hand.
        """
        for appt_type in self.mapped('booking_appointment_type_id'):
            if appt_type and appt_type.avatars_display != 'show':
                # sudo(): a recruiter editing the stage config may lack write
                # access to appointment.type; this is a system-policy default.
                appt_type.sudo().avatars_display = 'show'
