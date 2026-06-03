# -*- coding: utf-8 -*-
"""Public Appointments booking-form overrides for the Call Stage flow.

When a recruiter drags a candidate onto a Call Stage, the emailed booking
link carries an ``invite_token`` (the ``appointment.invite.access_token``).
That invite is already linked to the ``hr.applicant`` via ``applicant_id``
(shipped by ``appointment_hr_recruitment``). We use that link to:

* pre-fill the public booking form's Name/Email/Phone from the candidate
  card and mark the present ones read-only (``recruitment_locked_fields``);
* additionally collect a messenger contact (Telegram or WhatsApp, chosen
  with a two-button switch) — pre-filled+locked when the card already holds
  one, otherwise required so the candidate must supply it;
* enforce those values server-side on submit so a tampered (read-only is
  only a client hint) POST cannot change them;
* write back the fields that were empty on the card with whatever the
  candidate typed (including the messenger), keeping the application record
  in sync.

For any non-recruitment booking (no token, invalid token, or an invite with
no applicant) every override is a transparent pass-through to ``super()`` —
the native flow is untouched. See ``GUIDANCE.md`` for the active contract.
"""
from odoo import http
from odoo.http import request
from odoo.addons.appointment.controllers.appointment import AppointmentController


class CallStageAppointmentController(AppointmentController):

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
    def _call_stage_applicant_from_token(self, invite_token):
        """Resolve the ``hr.applicant`` behind a booking ``invite_token``.

        Returns an empty ``hr.applicant`` recordset when there is no token,
        the token is unknown, or the invite is not linked to an applicant —
        callers treat that as "behave exactly like the native flow".
        """
        if not invite_token:
            return request.env['hr.applicant']
        invite = request.env['appointment.invite'].sudo().search(
            [('access_token', '=', invite_token)], limit=1)
        return invite.applicant_id.sudo() if invite.applicant_id else request.env['hr.applicant']

    @staticmethod
    def _call_stage_should_skip_details(applicant, appointment_type, locked):
        """True when the public "details" step has nothing left to ask.

        The second booking step ("Add more details about you") exists only to
        collect the attendee identity (name/email/phone) plus any custom
        questions and guests. For a recruitment booking where the candidate
        card already holds *all three* identity fields and the appointment
        type asks nothing else, that step is pure friction — so we skip it and
        confirm the booking straight from the slot click.

        Kept deliberately strict: if any identity field is missing on the card
        (-> still needs typing), if the messenger contact is empty on the card
        (-> the candidate must pick one and type it), or the type has custom
        questions, or guests are allowed (-> the candidate may want to add
        some), we fall back to rendering the form with the present fields
        locked, exactly as before.
        """
        if not applicant or not appointment_type:
            return False
        if not all(locked.get(key) for key in ('name', 'email', 'phone')):
            return False
        # A messenger contact that is empty on the card must be collected from
        # the candidate -> the details step is NOT empty, so never skip it.
        if not locked.get('messenger'):
            return False
        if appointment_type.question_ids:
            return False
        if appointment_type.allow_guests:
            return False
        return True

    @staticmethod
    def _call_stage_field_map(applicant):
        """Map a candidate card onto the form's name/email/phone keys.

        A key is considered "present" (-> pre-filled + locked + enforced)
        only when its value is truthy. Name comes from ``partner_name``
        only: ``hr.applicant.name`` is the application subject, not a person
        name, so it must never be used to lock the field.
        """
        return {
            'name': applicant.partner_name or '',
            'email': applicant.email_from or '',
            'phone': applicant.partner_phone or applicant.partner_mobile or '',
        }

    @staticmethod
    def _call_stage_messenger_from_card(applicant):
        """Return ``(messenger_type, messenger_value)`` from the candidate card.

        Kept separate from ``_call_stage_field_map`` because the messenger is a
        *pair* (kind + value), not a single string — folding it into the
        identity dict would complicate that clean truthiness loop. The contact
        counts as "present" only when the value is truthy: a stray type with no
        value is treated as empty (-> still asked for on the form).
        """
        return (applicant.messenger_type or '', applicant.messenger_value or '')

    @staticmethod
    def _call_stage_inject_panel_context(qcontext, applicant):
        """Surface the job/company/"what to expect" info for the right-hand
        booking panel (v17.0.17.0.0).

        Mutates ``qcontext`` in place with three keys the public
        ``appointment_meeting_details`` overrides read (all gated on
        ``recruitment_booking`` in the template, so they are only ever shown
        on a recruitment booking):

        * ``recruitment_job_name`` / ``recruitment_company_name`` — context
          under the appointment-type name so the candidate sees WHICH role and
          company the call is for.
        * ``recruitment_what_to_expect`` — the Call Stage config's free-text
          ``what_to_expect`` split into a clean list of bullet lines (blank
          lines stripped). Empty list -> the template hides the panel.

        The config is resolved with the model's own ``_get_current_call_config``
        helper (handles the "already advanced to Call Booked" fallback). Always
        defines the keys so the template inherit is safe even when there is no
        config / no text.

        Also surfaces ``recruitment_interviewer_positions`` — a ``{user_id:
        job title}`` map for the "You will also meet" panel. The position lives
        on the interviewer's ``hr.employee`` record, which the PUBLIC candidate
        rendering the page cannot read, so it is resolved here under ``sudo``
        and passed pre-computed (the template never touches hr.employee). Source
        priority: employee Job Title -> employee Job Position -> partner
        Function (legacy fallback), so a value shows whichever field HR filled.
        """
        qcontext['recruitment_job_name'] = applicant.job_id.name or ''
        qcontext['recruitment_company_name'] = (
            applicant.company_id.name
            or applicant.job_id.company_id.name
            or '')
        config = applicant._get_current_call_config()
        qcontext['recruitment_what_to_expect'] = [
            line.strip()
            for line in (config.what_to_expect or '').splitlines()
            if line.strip()
        ]
        positions = {}
        for user in applicant.call_interviewer_user_ids.sudo():
            employee = user.employee_id or user.employee_ids[:1]
            positions[user.id] = (
                employee.job_title
                or employee.job_id.name
                or user.partner_id.function
                or '')
        qcontext['recruitment_interviewer_positions'] = positions

    # ------------------------------------------------------------
    # GET /call_stage/interviewer/<id>/avatar — public interviewer photo
    # ------------------------------------------------------------
    @http.route('/call_stage/interviewer/<int:user_id>/avatar',
                type='http', auth='public', cors='*')
    def call_stage_interviewer_avatar(self, user_id, avatar_size=512):
        """Serve an additional interviewer's avatar on the public booking page.

        The native ``/appointment/<id>/avatar`` route only serves photos for
        users in ``staff_user_ids`` — but interviewers are deliberately kept
        OUT of that pool (they must not gate slot availability). So we mirror
        that route's public+sudo pattern with our own access gate: the photo is
        served only when the user is actually configured as an interviewer —
        either as a Call Stage default (``hr.job.stage.config``) or on a live
        applicant (``hr.applicant.call_interviewer_user_ids``). Any other user
        id falls back to the generic placeholder, so this never leaks arbitrary
        user avatars to the public.
        """
        user = request.env['res.users'].sudo().browse(int(user_id))
        is_interviewer = bool(
            request.env['hr.job.stage.config'].sudo().search_count(
                [('interviewer_user_ids', 'in', user.id)])
            or request.env['hr.applicant'].sudo().search_count(
                [('call_interviewer_user_ids', 'in', user.id)])
        )
        served = user if (user.exists() and is_interviewer) else request.env['res.users']
        try:
            size = int(avatar_size)
        except (TypeError, ValueError):
            size = 512
        field_name = 'avatar_%s' % (size if size in [128, 256, 512, 1024, 1920] else 512)
        return request.env['ir.binary']._get_image_stream_from(
            served,
            field_name=field_name,
            placeholder='mail/static/src/img/smiley/avatar.jpg',
        ).get_response()

    # ------------------------------------------------------------
    # GET /appointment/<id>/info  — pre-fill + lock flags
    # ------------------------------------------------------------
    @http.route()
    def appointment_type_id_form(self, appointment_type_id, date_time, duration,
                                 staff_user_id=None, resource_selected_id=None,
                                 available_resource_ids=None, asked_capacity=1, **kwargs):
        response = super().appointment_type_id_form(
            appointment_type_id, date_time, duration,
            staff_user_id=staff_user_id, resource_selected_id=resource_selected_id,
            available_resource_ids=available_resource_ids,
            asked_capacity=asked_capacity, **kwargs)

        applicant = self._call_stage_applicant_from_token(kwargs.get('invite_token'))
        # Only the rendered booking form carries a (mutable) qcontext; failure
        # paths (NotFound, redirects) have none -> leave them untouched.
        qcontext = getattr(response, 'qcontext', None)
        if qcontext is None:
            return response
        # Always define the keys so the template inherit is safe on the native
        # (non-recruitment) path too, where no field is locked and the phone
        # field stays visible/required.
        qcontext.setdefault('recruitment_locked_fields', {})
        qcontext.setdefault('recruitment_booking', False)
        qcontext.setdefault('recruitment_interviewers', request.env['res.users'])
        qcontext.setdefault('recruitment_interviewer_positions', {})
        qcontext.setdefault('recruitment_job_name', '')
        qcontext.setdefault('recruitment_company_name', '')
        qcontext.setdefault('recruitment_what_to_expect', [])
        if not applicant:
            return response
        qcontext['recruitment_booking'] = True
        qcontext['recruitment_interviewers'] = applicant.call_interviewer_user_ids
        self._call_stage_inject_panel_context(qcontext, applicant)

        values = self._call_stage_field_map(applicant)
        partner_data = dict(qcontext.get('partner_data') or {})
        locked = {}
        for key in ('name', 'email', 'phone'):
            if values[key]:
                partner_data[key] = values[key]
                locked[key] = True
            else:
                locked[key] = False
        # Messenger (kind + value): pre-fill + lock when the card holds a
        # value, otherwise leave it required-but-empty for the candidate.
        m_type, m_value = self._call_stage_messenger_from_card(applicant)
        if m_value:
            partner_data['messenger_type'] = m_type
            partner_data['messenger_value'] = m_value
            locked['messenger'] = True
        else:
            locked['messenger'] = False
        qcontext['partner_data'] = partner_data
        qcontext['recruitment_locked_fields'] = locked

        # When the card already holds the full identity and the type asks
        # nothing else, the details step is empty -> confirm immediately.
        # ``appointment_form_submit`` re-validates the slot (capacity/staff
        # races redirect to a "state=failed-*" page) and returns the redirect
        # to the confirmation page, which the browser follows transparently
        # since the slot click is a full navigation to this GET route.
        appointment_type = qcontext.get('appointment_type')
        if self._call_stage_should_skip_details(applicant, appointment_type, locked):
            # We only skip when the messenger is present-on-card, so the submit
            # override re-enforces it from the card regardless; we still forward
            # the card values so the POST-like call carries them explicitly.
            return self.appointment_form_submit(
                appointment_type_id, date_time, duration,
                values['name'], values['phone'], values['email'],
                staff_user_id=staff_user_id,
                available_resource_ids=available_resource_ids,
                asked_capacity=asked_capacity,
                guest_emails_str=None,
                messenger_type=m_type, messenger_value=m_value,
                **kwargs)
        return response

    # ------------------------------------------------------------
    # GET /appointment/<id>  — slot-selection (calendar) page
    # ------------------------------------------------------------
    def _get_appointment_type_page_view(self, appointment_type, page_values, state=False, **kwargs):
        """Surface the candidate's name/email on the calendar page.

        The native flow only collects the attendee identity on the second
        ("Add more details about you") step. For a recruitment booking the
        candidate is already known from the invite token, so we expose their
        name/email to the template — rendered prominently above the calendar —
        and flag the page so the calendar/availability columns switch to the
        side-by-side layout earlier (see appointment_templates.xml).

        Non-recruitment bookings keep ``recruitment_booking`` falsy and render
        exactly as before.
        """
        response = super()._get_appointment_type_page_view(
            appointment_type, page_values, state=state, **kwargs)
        qcontext = getattr(response, 'qcontext', None)
        if qcontext is None:
            return response
        qcontext.setdefault('recruitment_booking', False)
        qcontext.setdefault('recruitment_interviewers', request.env['res.users'])
        qcontext.setdefault('recruitment_interviewer_positions', {})
        qcontext.setdefault('recruitment_job_name', '')
        qcontext.setdefault('recruitment_company_name', '')
        qcontext.setdefault('recruitment_what_to_expect', [])
        applicant = self._call_stage_applicant_from_token(kwargs.get('invite_token'))
        if not applicant:
            return response
        values = self._call_stage_field_map(applicant)
        qcontext['recruitment_booking'] = True
        qcontext['recruitment_candidate_name'] = values['name']
        qcontext['recruitment_candidate_email'] = values['email']
        qcontext['recruitment_interviewers'] = applicant.call_interviewer_user_ids
        self._call_stage_inject_panel_context(qcontext, applicant)
        return response

    # ------------------------------------------------------------
    # POST /appointment/<id>/submit  — enforce + write-back
    # ------------------------------------------------------------
    @http.route()
    def appointment_form_submit(self, appointment_type_id, datetime_str, duration_str,
                                name, phone, email, staff_user_id=None,
                                available_resource_ids=None, asked_capacity=1,
                                guest_emails_str=None, **kwargs):
        applicant = self._call_stage_applicant_from_token(kwargs.get('invite_token'))
        write_back = {}
        if applicant:
            values = self._call_stage_field_map(applicant)
            # ENFORCE: ignore client-submitted values for fields the card
            # already holds. The whole downstream flow (partner + event) is
            # built from these locals, so forcing them here is the real lock.
            if values['name']:
                name = values['name']
            else:
                write_back['partner_name'] = name
            if values['email']:
                email = values['email']
            else:
                write_back['email_from'] = email
            if values['phone']:
                phone = values['phone']
            else:
                write_back['partner_phone'] = phone
            # Messenger: enforce from the card when present (ignore whatever the
            # client posted); otherwise persist the candidate's choice, but only
            # as a complete, valid (type + value) pair — a value without a known
            # type, or vice versa, is dropped rather than half-written.
            _card_m_type, card_m_value = self._call_stage_messenger_from_card(applicant)
            if not card_m_value:
                post_m_type = (kwargs.get('messenger_type') or '').strip()
                post_m_value = (kwargs.get('messenger_value') or '').strip()
                if post_m_value and post_m_type in ('telegram', 'whatsapp'):
                    write_back['messenger_type'] = post_m_type
                    write_back['messenger_value'] = post_m_value
            # Only persist non-empty candidate input for empty-on-card fields.
            write_back = {k: v for k, v in write_back.items() if v}

        response = super().appointment_form_submit(
            appointment_type_id, datetime_str, duration_str, name, phone, email,
            staff_user_id=staff_user_id, available_resource_ids=available_resource_ids,
            asked_capacity=asked_capacity, guest_emails_str=guest_emails_str, **kwargs)

        # Write back only when the booking actually succeeded. Capacity/staff
        # clashes redirect to a "state=failed-*" URL instead of confirming.
        if applicant and write_back and not self._call_stage_is_failed_redirect(response):
            applicant.write(write_back)
        return response

    @staticmethod
    def _call_stage_is_failed_redirect(response):
        """True when ``appointment_form_submit`` bounced on a failed slot."""
        location = getattr(response, 'location', '') or ''
        return 'state=failed' in location

    # ------------------------------------------------------------
    # Customer partner resolution  — bind to the candidate's contact
    # ------------------------------------------------------------
    def _get_customer_partner(self):
        """Bind a recruitment booking to the candidate's own contact.

        The native ``appointment_form_submit`` resolves the attendee with
        ``self._get_customer_partner() or res.partner.search([('email', '=like',
        email)], limit=1)``. For a PUBLIC candidate this falls through to an
        *arbitrary* email match, and if that partner happens to own a user
        account the native guard raises ``"Please connect to book the
        appointment"`` — blocking a legitimate, token-proven booking.

        For a recruitment booking we instead return the candidate's own
        ``hr.applicant.partner_id`` (created userless by
        ``_ensure_partner_for_booking``), which is the correct attendee anyway
        and clears the guard because it owns no user. ``sudo`` so the public
        env can read it (the native ``appointment_type_id_form`` reads
        name/phone/email off this partner) and so the downstream write-backs
        succeed. Logged-in and non-recruitment bookings keep the native path.
        """
        partner = super()._get_customer_partner()
        if partner:
            return partner
        applicant = self._call_stage_applicant_from_token(
            request.params.get('invite_token'))
        if applicant and applicant.partner_id:
            return applicant.partner_id.sudo()
        return partner
