# -*- coding: utf-8 -*-
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


# Payload fields that distinguish an "override" config row from an "auto" row
# created as a side-effect of scope='specific'. Auto-rows are safe to delete
# when a stage flips back to 'global'; override-rows preserve user data.
#
# Downstream modules that add per-(job, stage) payload MUST extend this tuple
# in the same release bundle as the new field, otherwise the scope-flip
# cleanup in hr_recruitment_stage._inverse_scope will silently unlink rows
# whose only meaningful state lives in the new column.
_PAYLOAD_FIELDS = (
    'mail_template_id',
    'test_task_description',
    'booking_link_url',
    'requirements',
    'color',
    'legend_normal',
    'legend_blocked',
    'legend_done',
    'fold',
    # v17.0.1.0.13 — reserved hooks for hr_recruitment_call_stage (PR 5).
    # Names are kept here even though the columns are declared in the
    # sub-module via _inherit, because _has_payload() walks self[name] and
    # would silently skip any name absent from this tuple. See
    # docs/recruitment_calendar_booking.md §3.2 for the rationale.
    'is_call_stage',
    'booking_appointment_type_id',
    'call_booked_stage_id',
    # v17.0.6.0.0 reservation (hr_recruitment_call_stage Etap 7) —
    # recruiter pool that drives appointment.type.staff_user_ids.
    'recruiter_user_ids',
    # Reservation for hr_recruitment_fireflies (Phase 2) — per-(job, stage)
    # default interview questions (Text, one per line) seeded into a new
    # interview's recruiter questions. Column is declared in that module via
    # _inherit; the name is reserved here so scope-flip cleanup counts it as
    # payload and never drops a config row whose only data is these questions.
    'interview_question_template',
)


class HrJobStageConfig(models.Model):
    _name = 'hr.job.stage.config'
    _description = 'Per-job stage configuration'
    _order = 'sequence, stage_id'

    job_id = fields.Many2one(
        'hr.job', string='Job',
        required=True, ondelete='cascade', index=True)
    stage_id = fields.Many2one(
        'hr.recruitment.stage', string='Stage',
        required=True, ondelete='cascade', index=True)

    sequence = fields.Integer(
        string='Sequence', default=10, index=True,
        help='Per-job ordering of stages (drag-handle in the job form).')

    visible = fields.Boolean(
        string='Visible in Kanban', default=True,
        help='Uncheck to hide this stage column for this job only. '
             'Existing applicants on a hidden stage remain reachable via the '
             "job's Stages tab and via the kanban 'show hidden' search filter.")

    mail_template_id = fields.Many2one(
        'mail.template', string='Email Template (per-job override)',
        domain="[('model', '=', 'hr.applicant')]",
        help='If set, applicants moved to this stage on this job receive this '
             "template instead of the global stage template. Source of truth "
             "for per-job overrides.")
    effective_mail_template_id = fields.Many2one(
        'mail.template',
        compute='_compute_effective_mail_template_id',
        string='Currently used',
        help='Resolved template used by tracking: per-job override if any, '
             'otherwise falls back to stage.template_id.')
    effective_mail_template_source = fields.Char(
        compute='_compute_effective_mail_template_id',
        string='Template source',
        help='Indicates whether the currently used template comes from the '
             'per-job override or from the stage default.')

    test_task_description = fields.Html(
        string='Test Task Description (per-job)',
        sanitize=True,
        help='Reserved for PR 4. Per-job override of the test-task body '
             'rendered in the applicant invitation email.')

    link_ids = fields.One2many(
        'hr.job.stage.config.link', 'config_id',
        string='Resource Links',
        copy=True,
        help='Reserved for PR 4. Per-(job × stage) named URLs (git repo, '
             'specification, sample data) rendered in the test-task email '
             "and applicant form. Orthogonal to hr_recruitment_test_task's "
             'submission portal URL.')

    booking_link_url = fields.Char(
        string='Booking URL (fallback)',
        help='Reserved for PR 5. Generic calendar/booking URL fallback when '
             'the appointment module is not installed.')

    fold = fields.Boolean(
        string='Folded in Kanban (per-job)', default=False,
        help='Per-job fold override. Stock Odoo fold is global on the stage; '
             'this lets a job-specific stage be folded only for that job.')
    color = fields.Integer(
        string='Color (per-job)',
        help='Reserved for kanban column color per job.')

    legend_normal = fields.Char(
        string='Grey Kanban Label (per-job)',
        help='Reserved per-job override of stage.legend_normal.')
    legend_blocked = fields.Char(
        string='Red Kanban Label (per-job)',
        help='Reserved per-job override of stage.legend_blocked.')
    legend_done = fields.Char(
        string='Green Kanban Label (per-job)',
        help='Reserved per-job override of stage.legend_done.')

    requirements = fields.Text(
        string='Requirements (per-job override)',
        help='Reserved per-job override of stage.requirements; rendered as '
             "tooltip / accordion content in the job's Stages tab.")

    external_id_mapping = fields.Char(
        string='External ID Mapping', index=True,
        help='Reserved for future Genio ATS sync — left blank in PR 1b.')

    display_stage_name = fields.Char(
        related='stage_id.name', string='Stage Name',
        store=False, readonly=True)

    stage_scope = fields.Selection(
        related='stage_id.scope', string='Stage Scope',
        store=False, readonly=True,
        help='Mirror of the underlying stage.scope — used only by the job '
             "form Stages tab to decorate global rows and group/filter by "
             'scope. Not persisted; flips automatically with stage.scope.')

    company_id = fields.Many2one(
        related='job_id.company_id', store=True, readonly=True,
        string='Company')

    applicant_count = fields.Integer(
        string='Applicants on this stage',
        compute='_compute_applicant_count',
        help='Number of applicants currently sitting on this (job, stage) '
             'pair. Used by the hide-stage safety popup so the user can '
             'never silently drop a stage that still holds candidates.')

    _sql_constraints = [
        ('job_stage_uniq', 'UNIQUE(job_id, stage_id)',
         'A job can only have one configuration row per stage.'),
    ]

    @api.depends('mail_template_id', 'stage_id.template_id')
    def _compute_effective_mail_template_id(self):
        for config in self:
            if config.mail_template_id:
                config.effective_mail_template_id = config.mail_template_id
                config.effective_mail_template_source = _('(per-job override)')
            elif config.stage_id.template_id:
                config.effective_mail_template_id = config.stage_id.template_id
                config.effective_mail_template_source = _('(stage default)')
            else:
                config.effective_mail_template_id = False
                config.effective_mail_template_source = _('(none)')

    @api.constrains('booking_link_url')
    def _check_booking_link_url(self):
        pattern = re.compile(r'^https?://', re.IGNORECASE)
        for config in self:
            if config.booking_link_url and not pattern.match(config.booking_link_url):
                raise ValidationError(_(
                    "Booking URL '%s' must start with http:// or https://.",
                    config.booking_link_url,
                ))

    @api.constrains('mail_template_id')
    def _check_mail_template_model(self):
        # Blocks the recruiter from saving a config row that points at a
        # mail.template without model_id, or whose model is not
        # hr.applicant. Without this guard, the template renderer crashes
        # at self.env[self.model] with KeyError: False when an applicant
        # is moved through the stage.
        for config in self:
            tmpl = config.mail_template_id
            if not tmpl:
                continue
            if not tmpl.model_id or tmpl.model != 'hr.applicant':
                raise ValidationError(_(
                    "Email template '%(tmpl)s' is not configured for "
                    "applicants (model = %(model)s). Pick a template "
                    "whose Model is set to 'Applicant'.",
                    tmpl=tmpl.display_name,
                    model=tmpl.model or _('(not set)'),
                ))

    def _has_payload(self):
        self.ensure_one()
        if self.link_ids:
            return True
        # _PAYLOAD_FIELDS lists names declared by either this module or a
        # downstream module that has been installed. Skip names whose field
        # is not present on the current registry — without this guard, a
        # foundation-only install would crash on scope-flip cleanup as soon
        # as a new sub-module name was added to the tuple.
        for field_name in _PAYLOAD_FIELDS:
            if field_name not in self._fields:
                continue
            value = self[field_name]
            if isinstance(value, models.BaseModel):
                if value:
                    return True
            elif value not in (False, '', 0, None):
                return True
        return False

    def name_get(self):
        return [(c.id, '%s / %s' % (c.job_id.display_name, c.stage_id.name)) for c in self]

    @api.depends('job_id', 'stage_id')
    def _compute_applicant_count(self):
        Applicant = self.env['hr.applicant'].sudo()
        groups = Applicant.with_context(active_test=False)._read_group(
            domain=[
                ('job_id', 'in', self.job_id.ids),
                ('stage_id', 'in', self.stage_id.ids),
            ],
            groupby=['job_id', 'stage_id'],
            aggregates=['__count'],
        )
        counts = {(job.id, stage.id): n for job, stage, n in groups}
        for config in self:
            config.applicant_count = counts.get(
                (config.job_id.id, config.stage_id.id), 0)

    def action_toggle_visible(self):
        """Toggle visible from the Stages tab.

        Safe path: empty (job, stage) → silent flip.
        Risky path: applicants still on stage → return a confirm wizard
        that the user must accept. Applicants are NEVER deleted; they
        keep their stage_id and remain reachable via the kanban 'show
        hidden' filter and the Stages tab itself.
        """
        self.ensure_one()
        if not self.visible:
            # turning visible ON is always safe — no confirmation needed
            self.visible = True
            return True
        if self.applicant_count == 0:
            self.visible = False
            return True
        # has applicants → confirm wizard
        return {
            'type': 'ir.actions.act_window',
            'name': 'Confirm hide stage',
            'res_model': 'hr.job.stage.config.hide.confirm',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_config_id': self.id,
                'default_applicant_count': self.applicant_count,
            },
        }
