# -*- coding: utf-8 -*-
import logging

from markupsafe import Markup, escape

from odoo import _, api, models

_logger = logging.getLogger(__name__)

# Visible sentinel that survives the calendar.event.description HTML
# sanitizer (data-/class attributes are stripped, plain text is not), so a
# defensive second pass never duplicates the recruitment block.
_DESC_MARKER = 'Odoo Candidate Link:'


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
        """Append the recruitment block to the booked event's description.

        Keeps the stock booking-form data (Phone + Email) verbatim and adds,
        for applicant-linked events only:

        * Odoo Candidate Link — backend link to the hr.applicant record.
        * Cancel / Reschedule — public portal links (same routes the booking
          confirmation page uses).
        * Job Posting — the public website URL, only when the job is
          published (and the website_hr_recruitment field is present).

        Non-recruitment events are left untouched.
        """
        self.ensure_one()
        applicant = self.applicant_id
        if not applicant or not self.appointment_type_id:
            return
        # Idempotency guard: never append twice.
        if self.description and _DESC_MARKER in (self.description or ''):
            return

        base_url = self.get_base_url()
        partner = self.partner_id or self.appointment_booker_id
        token = self.access_token

        rows = []
        candidate_link = '%s/web#id=%s&model=hr.applicant&view_type=form' % (
            base_url, applicant.id,
        )
        rows.append(
            Markup('<li>%s <a href="%s">%s</a></li>') % (
                _DESC_MARKER, candidate_link,
                applicant.display_name or _('Candidate'),
            )
        )

        if token and partner:
            view_url = '%s/calendar/view/%s?partner_id=%s' % (
                base_url, token, partner.id,
            )
            cancel_url = '%s/calendar/%s/cancel?partner_id=%s' % (
                base_url, token, partner.id,
            )
            rows.append(
                Markup(
                    '<li>Reschedule: <a href="%s">Reschedule this call</a>'
                    '</li>'
                ) % view_url
            )
            rows.append(
                Markup(
                    '<li>Cancel: <a href="%s">Cancel this call</a></li>'
                ) % cancel_url
            )

        job = applicant.job_id
        # `website_url` only exists when website_hr_recruitment is installed;
        # soft-check the field so this module does not force that dependency.
        if (
            job
            and 'website_url' in job._fields
            and job.website_published
            and job.website_url
        ):
            job_url = job.get_base_url() + job.website_url
            rows.append(
                Markup('<li>Job Posting: <a href="%s">%s</a></li>') % (
                    job_url, escape(job.name or ''),
                )
            )

        block = (
            Markup('<div><ul>')
            + Markup('').join(rows)
            + Markup('</ul></div>')
        )
        new_description = (self.description or Markup('')) + block
        self.sudo().write({'description': new_description})

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
        """Build the candidate-facing plaintext ICS DESCRIPTION.

        This is what Google Calendar shows when the candidate opens the
        meeting invite, so it speaks in their perspective: who they are
        meeting, when, what to expect, who their recruiter is, and the
        self-service reschedule/cancel links. Plaintext only (``\\n`` joins,
        no Markup/HTML) because ICS DESCRIPTION is not rendered as HTML.
        """
        self.ensure_one()
        applicant = self.applicant_id
        job = applicant.job_id
        company = (applicant.company_id or self.env.company).name

        sections = []

        # Section 1 — Header
        header = [_("Interview with %(company)s", company=company)]
        if job and job.name:
            header.append(job.name)
        sections.append('\n'.join(header))

        # Section 2 — Meeting info
        meeting = []
        if self.start:
            # self.start is a naive UTC datetime; label it as such.
            when = self.start.strftime('%A, %B %-d at %-I:%M %p UTC')
            meeting.append('📅 %s' % when)
        if self.duration:
            meeting.append('⏱ %s' % self._call_stage_format_duration(self.duration))
        meeting.append('💻 Online (Google Meet)')
        sections.append('\n'.join(meeting))

        # Section 3 — What to expect (only if configured)
        config = self.env['hr.job.stage.config'].sudo().search([
            ('job_id', '=', job.id),
            ('is_call_stage', '=', True),
            ('booking_appointment_type_id', '=', self.appointment_type_id.id),
        ], limit=1)
        what_to_expect = getattr(config, 'what_to_expect', None) or ''
        expect_lines = [
            line.strip() for line in what_to_expect.split('\n') if line.strip()
        ]
        if expect_lines:
            block = [_("WHAT TO EXPECT")]
            block.extend('• %s' % line for line in expect_lines)
            sections.append('\n'.join(block))

        # Section 4 — Your recruiter (only if a staff user is assigned)
        staff_user = self.appointment_type_id.staff_user_ids[:1]
        if staff_user:
            block = [_("YOUR RECRUITER"), staff_user.name or '']
            function = getattr(staff_user.partner_id, 'function', None) or ''
            if function:
                block.append(function)
            if staff_user.email:
                block.append(staff_user.email)
            sections.append('\n'.join(line for line in block if line))

        # Section 5 — Links (reuse the same routes as the backend block)
        base_url = self.get_base_url()
        partner = self.partner_id or self.appointment_booker_id
        token = self.access_token
        links = ['──────────────────────────']
        if token and partner:
            links.append('🔗 Reschedule: %s/calendar/view/%s?partner_id=%s' % (
                base_url, token, partner.id,
            ))
            links.append('❌ Cancel: %s/calendar/%s/cancel?partner_id=%s' % (
                base_url, token, partner.id,
            ))
        if (
            job
            and 'website_url' in job._fields
            and job.website_published
            and job.website_url
        ):
            job_url = job.get_base_url() + job.website_url
            links.append('📄 View job description: %s' % job_url)
        sections.append('\n'.join(links))

        # Section 6 — Footer
        recruiter_email = staff_user.email if staff_user else ''
        if recruiter_email:
            footer = _(
                "Having trouble? Reply to this email or contact %(email)s.",
                email=recruiter_email,
            )
        else:
            footer = _("Having trouble? Reply to this email.")
        sections.append('──────────────────────────\n%s' % footer)

        return '\n\n'.join(sections)

    @staticmethod
    def _call_stage_format_duration(hours):
        """Format a float-hours duration as a human phrase (e.g. "1 hour",
        "30 minutes", "1.5 hours")."""
        if hours == int(hours):
            h = int(hours)
            return "%d hour" % h if h == 1 else "%d hours" % h
        minutes = round(hours * 60)
        if minutes < 60:
            return "%d minutes" % minutes
        return "%.1f hours" % hours
