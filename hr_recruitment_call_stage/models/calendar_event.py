# -*- coding: utf-8 -*-
import logging
import uuid

from markupsafe import Markup, escape

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# Hidden, candidate-safe idempotency sentinel embedded in the synced
# description. `html_sanitize` keeps HTML comments (verified) — and it runs
# both on the field write AND on google_calendar's `_google_values` push —
# so the marker survives end-to-end while staying invisible to the
# candidate. (The old marker was a recruiter-only backend applicant link,
# which had no business showing on the candidate's calendar card.)
_DESC_SENTINEL = '<!-- hr_recruitment_call_stage:candidate-description -->'


class CalendarEvent(models.Model):
    _inherit = 'calendar.event'

    # Etap 2 (v17.0.2.0.0): the `applicant_id` field is no longer declared
    # here — it ships natively from `appointment_hr_recruitment` as a
    # stored related field on `appointment_invite_id.applicant_id`. We
    # only override `create` to keep the recruiter-friendly event title
    # (`<Candidate> — <Type>`) and to trigger auto-advance.

    @api.model_create_multi
    def create(self, vals_list):
        # Step 1: pre-create — rewrite event name for events that came
        # from a recruitment booking invite. The related `applicant_id`
        # will be set by Odoo from `appointment_invite_id.applicant_id`
        # during the super() create; we look up the applicant directly
        # for the name rewrite because the related store hasn't run yet.
        AppointmentInvite = self.env['appointment.invite'].sudo()
        for vals in vals_list:
            invite_id = vals.get('appointment_invite_id')
            if not invite_id:
                continue
            invite = AppointmentInvite.browse(invite_id)
            applicant = invite.applicant_id
            if not applicant:
                continue
            # Belt-and-braces: the native related stored field will fill
            # itself from appointment_invite_id.applicant_id during the
            # super() flush, but writing it explicitly here keeps the in-
            # memory record consistent for the auto-advance hook below.
            vals['applicant_id'] = applicant.id
            appt_type_id = vals.get('appointment_type_id')
            appt_type = (
                self.env['appointment.type'].browse(appt_type_id)
                if appt_type_id else self.env['appointment.type']
            )
            candidate_label = (
                applicant.partner_name or applicant.name or _('Candidate')
            )
            appt_label = appt_type.name if appt_type else _('Interview')
            # Override the stock "<attendee> - <appointment> Booking" naming
            # (see appointment_type.py:984) with the recruiter-friendly
            # "Candidate — Type" format. Done once at create; reschedules
            # (write calls) keep whatever title the recruiter chose later.
            vals['name'] = '%s — %s' % (candidate_label, appt_label)

            # Pre-seed the rich, candidate-facing description into the field
            # Google Calendar actually syncs FROM — calendar.event.description
            # (see google_calendar/models/calendar.py `_google_values`, which
            # sends `html_sanitize(self.description)`). Setting it here in the
            # create vals means the very FIRST push to Google
            # (`google.calendar.sync.create` → `_google_insert`, which runs
            # inside super().create) already carries the rich content. That
            # avoids the previous race: enrichment used to run AFTER create, so
            # Google's initial insert captured the bare Phone/Email body and a
            # failed/slow `_google_patch` could let that stale body win on the
            # next google→odoo pull. The ICS path (`_get_customer_description`)
            # is never read by Google, so the rich content had to land here.
            #
            # access_token is pre-generated so the reschedule/cancel links
            # resolve; the stock lazy generator (calendar.py
            # `_set_discuss_videocall_location`) is a no-op once it is set, so
            # the value stays stable for the Meet redirection link too.
            if not vals.get('access_token'):
                vals['access_token'] = uuid.uuid4().hex
            start = fields.Datetime.to_datetime(vals.get('start'))
            stop = fields.Datetime.to_datetime(vals.get('stop'))
            duration = vals.get('duration')
            if duration is None and start and stop:
                duration = (stop - start).total_seconds() / 3600.0
            booker_id = vals.get('appointment_booker_id')
            partner = (
                self.env['res.partner'].browse(booker_id)
                if booker_id else self.env['res.partner']
            )
            ctx = self._call_stage_description_context(
                applicant=applicant, appt_type=appt_type,
                start=start, stop=stop, duration=duration,
                base_url=self.get_base_url(),
                token=vals['access_token'], partner=partner,
            )
            vals['description'] = self._call_stage_render_description_html(ctx)

        records = super().create(vals_list)

        # Step 2: post-create — enrich the event description with the
        # recruitment block (candidate link, cancel/reschedule, job posting)
        # and auto-advance the applicant if the booking matches an active
        # Call Stage configuration. Description enrichment runs here (not in
        # `_prepare_calendar_event_values`) because the event now exists, so
        # `access_token` and the native related `applicant_id` are populated.
        for event in records:
            event._call_stage_enrich_description()
            event._call_stage_auto_advance_applicant()
            event._call_stage_add_interviewers()

        return records

    def _call_stage_add_interviewers(self):
        """Add the applicant's additional interviewers as event attendees.

        Source of truth is ``hr.applicant.call_interviewer_user_ids`` (seeded
        from the Call Stage default on stage entry, then recruiter-curated).
        Adding their partners to ``partner_ids`` makes Odoo create the
        ``calendar.attendee`` rows and send the standard invitation — which
        already carries the Google Meet link in ``videocall_location`` — so no
        separate minting is needed. Idempotent: ``(4, id)`` is a no-op when the
        partner is already an attendee (e.g. recruiter == interviewer, or a
        reschedule re-running on the same event).
        """
        self.ensure_one()
        applicant = self.applicant_id
        if not applicant or not self.appointment_type_id:
            return
        # Add-only path used at booking time. The reconcile method below is the
        # superset (handles removals too); creation has nothing to remove yet.
        self._call_stage_reconcile_interviewers(self.env['res.users'])

    def _call_stage_reconcile_interviewers(self, removed_users):
        """Reconcile this event's attendees with the applicant's current
        ``call_interviewer_user_ids``.

        Two directions, both idempotent:

        * **add** — every currently-listed interviewer whose partner is not yet
          an attendee is added (``(4, id)``), so they receive the calendar
          invite carrying the Google Meet link.
        * **remove** — every user in ``removed_users`` (interviewers just
          dropped from the applicant) is unlinked from ``partner_ids``
          (``(3, id)``), which deletes their ``calendar.attendee`` row and
          propagates the removal to Google Calendar on the next sync.

        ``removed_users`` is passed by the caller (it knows the old list); we
        never remove a partner that is still a current interviewer, the
        candidate, the booker, or the organiser, so a user who is both an
        interviewer and (say) the recruiter is never accidentally un-invited.
        """
        self.ensure_one()
        applicant = self.applicant_id
        if not applicant or not self.appointment_type_id:
            return
        current_partners = applicant.call_interviewer_user_ids.partner_id
        existing = self.partner_ids
        # Partners that must stay regardless of the interviewer delta.
        protected = (
            current_partners
            | applicant.partner_id
            | self.appointment_booker_id
            | self.user_id.partner_id
        )
        commands = []
        for partner in current_partners:
            if partner and partner not in existing:
                commands.append((4, partner.id))
        for partner in removed_users.partner_id:
            if partner and partner in existing and partner not in protected:
                commands.append((3, partner.id))
        if commands:
            self.sudo().write({'partner_ids': commands})

    def _call_stage_enrich_description(self):
        """Safety net that writes the rich candidate-facing description.

        The booking path seeds this in the create vals (see ``create``), so
        for normal bookings the sentinel is already present and this is a
        no-op. It still runs as a defensive second pass for any applicant-
        linked event that reaches post-create without the rich body, in which
        case it REPLACES the stock Phone/Email body entirely with the same
        HTML the candidate sees on their Google Calendar card.

        Non-recruitment events are left untouched.
        """
        self.ensure_one()
        applicant = self.applicant_id
        if not applicant or not self.appointment_type_id:
            return
        # Idempotency guard: the booking path already wrote the rich body.
        if self.description and _DESC_SENTINEL in (self.description or ''):
            return
        ctx = self._call_stage_description_context(
            applicant=applicant, appt_type=self.appointment_type_id,
            start=self.start, stop=self.stop, duration=self.duration,
            base_url=self.get_base_url(),
            token=self.access_token,
            partner=self.partner_id or self.appointment_booker_id,
        )
        self.sudo().write({
            'description': self._call_stage_render_description_html(ctx),
        })

    def _call_stage_rerender_description(self):
        """Re-render and overwrite the synced description from current values.

        Unlike ``_call_stage_enrich_description`` this ignores the idempotency
        sentinel — it is called from ``write`` after a reschedule so the
        date/time the candidate sees on their Google Calendar invite is
        refreshed. The inner write only touches ``description`` (never
        start/stop), so it does not re-trigger the reschedule branch.
        """
        self.ensure_one()
        if not self.applicant_id or not self.appointment_type_id:
            return
        ctx = self._call_stage_description_context(
            applicant=self.applicant_id, appt_type=self.appointment_type_id,
            start=self.start, stop=self.stop, duration=self.duration,
            base_url=self.get_base_url(),
            token=self.access_token,
            partner=self.partner_id or self.appointment_booker_id,
        )
        self.sudo().write({
            'description': self._call_stage_render_description_html(ctx),
        })

    def write(self, vals):
        # Reschedule auditing — log a chatter note on the applicant when the
        # start/stop datetime of an applicant-linked event changes. We do
        # this BEFORE super() to capture the previous datetime.
        old_starts = {
            event.id: event.start
            for event in self
            if event.applicant_id and 'start' in vals
        }
        res = super().write(vals)
        if old_starts:
            for event in self:
                old_start = old_starts.get(event.id)
                new_start = event.start
                if not old_start or old_start == new_start:
                    continue
                event.applicant_id.message_post(body=_(
                    "Call rescheduled: %(old)s → %(new)s",
                    old=old_start, new=new_start,
                ))
        # Reschedule freshness: when the schedule moved, re-render the synced
        # description so the date/time on the candidate's Google Calendar card
        # stays accurate. Skipped when the caller already set `description`
        # (e.g. the inner write below) to avoid clobbering an explicit value.
        if ('start' in vals or 'stop' in vals) and 'description' not in vals:
            for event in self:
                if event.applicant_id and event.appointment_type_id:
                    event._call_stage_rerender_description()
        return res

    def _call_stage_auto_advance_applicant(self):
        """Advance the linked applicant to call_booked_stage_id when the
        booking confirms a Call Stage flow.

        R2: this is the ONLY place hr_recruitment_call_stage mutates
        hr.applicant.stage_id. Race-safe — only fires when applicant is
        still on the matching Call Stage AND the event's appointment type
        matches the config.
        """
        self.ensure_one()
        applicant = self.applicant_id
        if not applicant:
            return
        if not self.appointment_type_id:
            return
        # Etap 1 gate: archived or refused applicants cannot be resurrected
        # by a stale booking link the candidate still holds. Silent no-op
        # — they are out of the funnel by recruiter decision.
        if not applicant.active or applicant.refuse_reason_id:
            return
        # Etap 1 race-safety: lock the applicant row before reading stage,
        # so a concurrent recruiter stage-change cannot produce a lost
        # update on stage_id. Re-read after the lock.
        self.env.cr.execute(
            'SELECT id FROM hr_applicant WHERE id = %s FOR UPDATE',
            (applicant.id,),
        )
        applicant.invalidate_recordset(['stage_id'])
        config = self.env['hr.job.stage.config'].sudo().search([
            ('job_id', '=', applicant.job_id.id),
            ('stage_id', '=', applicant.stage_id.id),
            ('is_call_stage', '=', True),
        ], limit=1)
        if not config:
            # Applicant already moved by a recruiter, or the booking landed
            # on a stage that isn't a Call Stage. Log and stop.
            applicant.message_post(body=_(
                "Booking confirmed for %(start)s but the applicant is no "
                "longer on a Call Stage — auto-advance skipped.",
                start=self.start,
            ))
            return
        if config.booking_appointment_type_id != self.appointment_type_id:
            # Wrong appointment type for this stage — don't advance.
            return
        if not config.call_booked_stage_id:
            _logger.warning(
                "hr_recruitment_call_stage: Call Stage config id=%s is "
                "missing call_booked_stage_id; not advancing applicant "
                "id=%s.", config.id, applicant.id,
            )
            return
        target_stage = config.call_booked_stage_id
        applicant.sudo().with_context(
            mail_auto_subscribe_no_notify=True,
        ).stage_id = target_stage.id
        applicant.message_post(body=_(
            "Call booked at %(start)s — moved to stage '%(stage)s'.",
            start=self.start,
            stage=target_stage.display_name,
        ))

    # ------------------------------------------------------------------
    # Smart button on the event form
    # ------------------------------------------------------------------
    def action_open_applicant(self):
        self.ensure_one()
        if not self.applicant_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': self.applicant_id.display_name,
            'res_model': 'hr.applicant',
            'res_id': self.applicant_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # ICS — candidate-friendly SUMMARY
    # ------------------------------------------------------------------
    def _get_customer_summary(self):
        # Override stock implementation (calendar_event.py:1464) only for
        # events we created from a booking — for everything else fall back
        # to super(). The in-Odoo `name` stays "<Candidate> — <Type>" for
        # the recruiter; the ICS sent to the candidate now reads in their
        # own perspective.
        self.ensure_one()
        if self.applicant_id and self.appointment_type_id:
            job = self.applicant_id.job_id
            # Etap 1 multi-company fix: ICS represents the applicant's
            # employer, not the request env's company (cross-company
            # recruiters were seeing the wrong brand on outbound ICS).
            company = (self.applicant_id.company_id or self.env.company).name
            if job:
                return _(
                    "Interview with %(company)s — %(job)s",
                    company=company, job=job.name,
                )
            return _("Interview with %(company)s", company=company)
        return super()._get_customer_summary()

    # ------------------------------------------------------------------
    # ICS — candidate-friendly DESCRIPTION
    # ------------------------------------------------------------------
    def _get_customer_description(self):
        # Override stock implementation (appointment/calendar_event.py:427)
        # only for events we created from a recruitment booking. The stock
        # body (message_confirmation + contact details) is useless to the
        # candidate — it just echoes their own phone/email back at them.
        # Everything else falls back to super().
        self.ensure_one()
        if self.applicant_id and self.appointment_type_id:
            return self._call_stage_get_customer_description()
        return super()._get_customer_description()

    def _call_stage_get_customer_description(self):
        """Candidate-facing plaintext ICS DESCRIPTION (the invitation email).

        Thin wrapper: builds the shared content context from this record and
        renders it as plaintext. The HTML twin of the same content lands in
        ``calendar.event.description`` (what Google Calendar reads).
        """
        self.ensure_one()
        ctx = self._call_stage_description_context(
            applicant=self.applicant_id, appt_type=self.appointment_type_id,
            start=self.start, stop=self.stop, duration=self.duration,
            base_url=self.get_base_url(),
            token=self.access_token,
            partner=self.partner_id or self.appointment_booker_id,
        )
        return self._call_stage_render_description_text(ctx)

    # ------------------------------------------------------------------
    # Shared candidate-description content (one source of truth)
    # ------------------------------------------------------------------
    def _call_stage_description_context(
        self, applicant, appt_type, start, stop, duration,
        base_url, token, partner,
    ):
        """Compute the render-agnostic pieces of the candidate-facing booking
        description, so the HTML renderer (the synced
        ``calendar.event.description`` Google reads) and the plaintext ICS
        renderer can never drift. Takes primitive inputs (not ``self``) so it
        works pre-create — before the record exists — straight from the
        create vals, as well as from a live record.
        """
        job = applicant.job_id
        company = (applicant.company_id or self.env.company).name
        config = self.env['hr.job.stage.config'].sudo().search([
            ('job_id', '=', job.id),
            ('is_call_stage', '=', True),
            ('booking_appointment_type_id', '=', appt_type.id),
        ], limit=1)
        what_to_expect = getattr(config, 'what_to_expect', None) or ''
        expect_lines = [
            line.strip() for line in what_to_expect.split('\n') if line.strip()
        ]
        staff_user = appt_type.staff_user_ids[:1]

        reschedule_url = cancel_url = job_url = ''
        if token and partner:
            reschedule_url = '%s/calendar/view/%s?partner_id=%s' % (
                base_url, token, partner.id,
            )
            cancel_url = '%s/calendar/%s/cancel?partner_id=%s' % (
                base_url, token, partner.id,
            )
        # `website_url` only exists when website_hr_recruitment is installed;
        # soft-check the field so this module does not force that dependency.
        if (
            job
            and 'website_url' in job._fields
            and job.website_published
            and job.website_url
        ):
            job_url = job.get_base_url() + job.website_url

        # Recruiter aid: candidate name + a deep-link to the applicant's
        # backend form. Shared (the candidate sees it on the synced card too)
        # but only resolves for internal users — labelled accordingly below.
        # Same name fallback as the event title (see `create`).
        candidate_name = (
            applicant.partner_name or applicant.name or _('Candidate')
        )
        candidate_url = ''
        if applicant.id:
            candidate_url = '%s/web#id=%s&model=hr.applicant&view_type=form' % (
                base_url, applicant.id,
            )

        return {
            'applicant': applicant, 'job': job, 'company': company,
            'start': start, 'stop': stop, 'duration': duration,
            'expect_lines': expect_lines, 'staff_user': staff_user,
            'reschedule_url': reschedule_url, 'cancel_url': cancel_url,
            'job_url': job_url,
            'candidate_name': candidate_name, 'candidate_url': candidate_url,
        }

    def _call_stage_render_description_text(self, ctx):
        """Render the shared context as the candidate-facing plaintext ICS
        DESCRIPTION — the plaintext twin of the HTML renderer below, kept
        structurally identical so the two layouts never drift. Plaintext only
        (``\\n`` joins); a single blank line separates each section.
        """
        job = ctx['job']
        company = ctx['company']
        sections = []

        # Section 1 — one-line confirmation (company + role). No date/time:
        # the calendar card already shows those in its own fields.
        if job and job.name:
            sections.append(_(
                "Your interview with %(company)s for the %(job)s role is "
                "confirmed.",
                company=company, job=job.name,
            ))
        else:
            sections.append(_(
                "Your interview with %(company)s is confirmed.",
                company=company,
            ))

        # Section 2 — What to expect: header then the notes directly beneath
        # it (no blank gap inside the section). Omitted when not filled in.
        if ctx['expect_lines']:
            sections.append('%s\n%s' % (
                _("What to expect"), '\n'.join(ctx['expect_lines']),
            ))

        # Section 3 — Position: inline label with the role. The public posting
        # URL sits on the next line when published (plaintext cannot link).
        if job and job.name:
            position = '%s %s' % (_("Position:"), job.name)
            if ctx['job_url']:
                position += '\n%s' % ctx['job_url']
            sections.append(position)

        # Section 4 — Self-service links: header then both links on one line,
        # separated by a middle dot. Only with a usable portal token.
        if ctx['reschedule_url']:
            sections.append('%s\n%s %s  ·  %s %s' % (
                _("Need to make a change?"),
                _("Reschedule:"), ctx['reschedule_url'],
                _("Cancel:"), ctx['cancel_url'],
            ))

        # Section 5 — Candidate: inline label with the name. The backend
        # deep-link is omitted in plaintext (it only resolves for internal
        # users and would be noise in the candidate's invitation email).
        if ctx['candidate_url']:
            sections.append('%s %s' % (
                _("Candidate:"), ctx['candidate_name'],
            ))

        return '\n\n'.join(sections)

    def _call_stage_render_description_html(self, ctx):
        """Render the shared context as sanitized HTML for the synced
        ``calendar.event.description`` (the field Google Calendar reads, and
        the body shown on the Odoo event form). A deliberately minimal layout:
        a one-line confirmation, an optional "What to expect" block (only when
        the Call Stage config fills it in), an inline Position label, the
        reschedule/cancel links, and an inline Candidate label. Each section is
        its own ``<p>`` so the card shows a single blank line between them; line
        breaks inside a section use ``<br/>``. The hidden idempotency sentinel
        is appended last. All interpolated user data is escaped (``Markup``
        ``%`` escapes its arguments).
        """
        job = ctx['job']
        company = ctx['company']
        blocks = []

        # Section 1 — one-line confirmation (company + role), plain text. No
        # date/time: the Google Calendar card already shows those in its own
        # fields.
        if job and job.name:
            confirm = _(
                "Your interview with %(company)s for the %(job)s role is "
                "confirmed.",
                company=company, job=job.name,
            )
        else:
            confirm = _(
                "Your interview with %(company)s is confirmed.",
                company=company,
            )
        blocks.append(Markup('<p>%s</p>') % confirm)

        # Section 2 — What to expect: bold header with the notes directly
        # beneath it. Omitted entirely when not filled in.
        if ctx['expect_lines']:
            body = Markup('<br/>').join(
                escape(line) for line in ctx['expect_lines']
            )
            blocks.append(
                Markup('<p><strong>%s</strong><br/>%s</p>')
                % (_("What to expect"), body)
            )

        # Section 3 — Position: inline bold label with the role (linked to the
        # public posting when published).
        if job and job.name:
            if ctx['job_url']:
                value = Markup('<a href="%s">%s</a>') % (ctx['job_url'], job.name)
            else:
                value = escape(job.name)
            blocks.append(
                Markup('<p><strong>%s</strong> %s</p>')
                % (_("Position:"), value)
            )

        # Section 4 — Self-service links: bold header with both links on the
        # next line, separated by a middle dot. Only with a usable portal token.
        if ctx['reschedule_url']:
            blocks.append(
                Markup('<p><strong>%s</strong><br/>'
                       '<a href="%s">%s</a> &nbsp;·&nbsp; '
                       '<a href="%s">%s</a></p>')
                % (_("Need to make a change?"),
                   ctx['reschedule_url'], _("Reschedule"),
                   ctx['cancel_url'], _("Cancel"))
            )

        # Section 5 — Candidate: inline bold label with the name. The backend
        # deep-link only resolves for internal users; kept as a plain
        # hyperlink on the name.
        if ctx['candidate_url']:
            value = Markup('<a href="%s">%s</a>') % (
                ctx['candidate_url'], ctx['candidate_name'],
            )
            blocks.append(
                Markup('<p><strong>%s</strong> %s</p>')
                % (_("Candidate:"), value)
            )

        return (
            Markup('<div>%s</div>') % Markup('').join(blocks)
            + Markup(_DESC_SENTINEL)
        )
