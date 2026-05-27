# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


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

    default_meeting_url = fields.Char(
        string='Default meeting URL',
        help='Optional fixed meeting room (e.g. a permanent Google Meet / '
             'Zoom link). When set, applicants on this Call Stage receive '
             'this URL in the invite email instead of an auto-minted '
             'Odoo Appointments link — unless the applicant has their own '
             'manual_meeting_url override. Leave blank to use Appointments.')

    # v17.0.6.0.0 — Etap 7: bind recruiter Odoo calendars to the booking pool.
    # When set, candidates booking through this Call Stage's appointment.type
    # see slots derived from these recruiters' internal Odoo calendars (the
    # native appointment.type.staff_user_ids mechanism). Sync semantics is
    # UNION across all configs sharing the same appointment.type — so two
    # stages that both reference appointment_type X with different recruiter
    # sets won't clobber each other.
    recruiter_user_ids = fields.Many2many(
        'res.users', 'hr_job_stage_config_recruiter_user_rel',
        'config_id', 'user_id',
        string='Booking calendars (recruiters)',
        domain="[('share', '=', False)]",
        help='Internal Odoo users whose calendars feed the booking pool '
             'for this Call Stage. On save we add them to the appointment '
             "type's staff_user_ids (UNION — we never remove recruiters "
             'added by other Call Stage configs that share this '
             'appointment type). Leave empty to rely on whatever the '
             "appointment type's staff list already contains.")

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
        res = super().write(vals)
        if rows_enabling:
            rows_enabling._sync_call_booked_membership()
            # v17.0.1.1.0: auto-fill the shipped call-invite template on rows
            # that have no per-job template yet. Vals-level skip honours an
            # explicit caller choice in the same write (recruiter set template
            # AND ticked is_call_stage in one save). Untick path is a no-op
            # by design — preserve any template the recruiter customised.
            if 'mail_template_id' not in vals:
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
            self.filtered(
                lambda c: c.is_call_stage and c.booking_appointment_type_id
            )._sync_recruiter_staff_users()
        return res

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
        records.filtered(
            lambda c: c.is_call_stage and c.booking_appointment_type_id
        )._sync_recruiter_staff_users()
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
        """Ensure each job in self.job_id is linked to the global
        Call Booked stage, and back-fill call_booked_stage_id.

        Race-safe: the foundation's write() override on
        hr.recruitment.stage auto-creates the (job, stage) config row when
        a job joins stage.job_ids (see foundation hr_recruitment_stage.py
        line 127). We use skip_inverse_scope to suppress the inverse so the
        row is created via _ensure_config_rows_for_jobs deterministically.
        """
        stage_cb = self.env.ref(
            _CALL_BOOKED_STAGE_XMLID, raise_if_not_found=False)
        if not stage_cb:
            # Module data missing (e.g. test running mid-install). Skip
            # silently — the constraint above already prevents a Call Stage
            # without an appointment type, so the email path stays safe.
            return
        jobs_to_link = self.mapped('job_id')
        if jobs_to_link:
            missing = jobs_to_link - stage_cb.job_ids
            if missing:
                stage_cb.with_context(skip_inverse_scope=True).write({
                    'job_ids': [(4, job.id) for job in missing],
                })
            # Foundation's _ensure_config_rows_for_jobs creates with
            # visible=True only when stage.default_visible_in_new_jobs would
            # not be consulted (i.e. for newly-added jobs to a specific
            # stage). For the global-stage path it falls back to
            # default_visible_in_new_jobs=False on our shipped Call Booked.
            # Force visible=True on the (job, Call Booked) row whenever a
            # job activates a Call Stage — visibility is opt-in per job
            # and this is the deliberate opt-in moment.
            cb_configs = self.env['hr.job.stage.config'].sudo().search([
                ('job_id', 'in', jobs_to_link.ids),
                ('stage_id', '=', stage_cb.id),
            ])
            cb_configs.filtered(lambda c: not c.visible).visible = True
        for config in self:
            if not config.call_booked_stage_id:
                # Bypass write() override to avoid re-entry into this method.
                # Auto-back-fill should not retrigger membership sync.
                super(HrJobStageConfig, config).write({
                    'call_booked_stage_id': stage_cb.id,
                })

    def _sync_recruiter_staff_users(self):
        """Push ``recruiter_user_ids`` into
        ``booking_appointment_type_id.staff_user_ids``.

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
        Config = self.env['hr.job.stage.config'].sudo()
        appt_types = self.mapped('booking_appointment_type_id')
        for appt_type in appt_types:
            sibling_configs = Config.search([
                ('is_call_stage', '=', True),
                ('booking_appointment_type_id', '=', appt_type.id),
            ])
            configs_with_recruiters = sibling_configs.filtered(
                'recruiter_user_ids')
            if not configs_with_recruiters:
                # Opt-out path — appointment.type is recruiter-managed
                # directly. Skip silently.
                continue
            target = configs_with_recruiters.mapped('recruiter_user_ids')
            if appt_type.staff_user_ids != target:
                appt_type.sudo().write({
                    'staff_user_ids': [(6, 0, target.ids)],
                })
