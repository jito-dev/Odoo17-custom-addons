# -*- coding: utf-8 -*-
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


# Payload fields that distinguish an "override" config row from an "auto" row
# created as a side-effect of scope='specific'. Auto-rows are safe to delete
# when a stage flips back to 'global'; override-rows preserve user data.
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
        string='Effective Email Template',
        help='Resolved template used by tracking: per-job override if any, '
             'otherwise falls back to stage.template_id.')

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
            config.effective_mail_template_id = (
                config.mail_template_id or config.stage_id.template_id
            )

    @api.constrains('booking_link_url')
    def _check_booking_link_url(self):
        pattern = re.compile(r'^https?://', re.IGNORECASE)
        for config in self:
            if config.booking_link_url and not pattern.match(config.booking_link_url):
                raise ValidationError(_(
                    "Booking URL '%s' must start with http:// or https://.",
                    config.booking_link_url,
                ))

    def _has_payload(self):
        self.ensure_one()
        if self.link_ids:
            return True
        for field_name in _PAYLOAD_FIELDS:
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
