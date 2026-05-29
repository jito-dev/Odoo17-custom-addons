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

        return records

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
