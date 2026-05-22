# -*- coding: utf-8 -*-
"""Wizard: create a job-specific stage from the job form.

Lets a recruiter spin up a new ``hr.recruitment.stage`` with
``scope='specific'`` and ``job_ids = [current job]``, optionally
seeded from a previously used job-specific stage (any stage that
has ``scope='specific'`` on at least one other job). Picking a
template copies the email template *from the source's config row*
(source-of-truth) rather than from ``stage.template_id``, so the
correct per-job email flows over to the new job.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrJobStageCreateWizard(models.TransientModel):
    _name = 'hr.job.stage.create.wizard'
    _description = 'Create a job-specific stage wizard'

    job_id = fields.Many2one(
        'hr.job', string='Job', required=True, readonly=True)

    template_source_id = fields.Many2one(
        'hr.recruitment.stage',
        string='Copy from existing job-specific stage',
        domain="[('scope', '=', 'specific'), ('job_ids', 'not in', [job_id])]",
        help='Optional. Pick a stage previously used on another job to '
             'pre-fill name, email template, requirements, test task and '
             'resource links. The new stage is independent; nothing is '
             'shared with the source.')
    template_source_config_id = fields.Many2one(
        'hr.job.stage.config',
        string='Source config row (resolved)',
        compute='_compute_template_source_config_id',
        help='Resolved per-(job, stage) config row from which to inherit '
             'the email template and other payload. We deliberately read '
             'this rather than stage.template_id so the per-job override '
             'wins.')

    name = fields.Char(string='Stage Name', required=True)
    sequence = fields.Integer(string='Sequence', default=50)
    mail_template_id = fields.Many2one(
        'mail.template', string='Email Template',
        domain="[('model', '=', 'hr.applicant')]")
    requirements = fields.Text(string='Requirements')
    test_task_description = fields.Html(
        string='Test Task Description', sanitize=True)
    link_ids = fields.One2many(
        'hr.job.stage.create.wizard.link', 'wizard_id',
        string='Resource Links')

    @api.depends('template_source_id', 'job_id')
    def _compute_template_source_config_id(self):
        Config = self.env['hr.job.stage.config'].sudo()
        for wiz in self:
            if not wiz.template_source_id:
                wiz.template_source_config_id = False
                continue
            # Pick any config row attached to that stage — they all share
            # the per-stage payload candidates. Most recent wins.
            wiz.template_source_config_id = Config.search([
                ('stage_id', '=', wiz.template_source_id.id),
            ], limit=1, order='id desc')

    @api.onchange('template_source_id')
    def _onchange_template_source_id(self):
        if not self.template_source_id:
            return
        stage = self.template_source_id
        self.name = stage.name
        self.sequence = stage.sequence
        src_cfg = self.template_source_config_id
        # mail template: prefer per-job override from source config row
        self.mail_template_id = (
            (src_cfg and src_cfg.mail_template_id) or stage.template_id
        )
        self.requirements = (src_cfg and src_cfg.requirements) or False
        self.test_task_description = (
            (src_cfg and src_cfg.test_task_description) or False
        )
        if src_cfg and src_cfg.link_ids:
            self.link_ids = [
                (0, 0, {
                    'label': link.label,
                    'url': link.url,
                    'sequence': link.sequence,
                })
                for link in src_cfg.link_ids
            ]
        else:
            self.link_ids = [(5, 0, 0)]

    def action_create(self):
        self.ensure_one()
        if not self.job_id:
            raise UserError(_("Job is required."))
        Stage = self.env['hr.recruitment.stage'].sudo()
        Config = self.env['hr.job.stage.config'].sudo()

        stage = Stage.create({
            'name': self.name,
            'sequence': self.sequence,
            'job_ids': [(6, 0, [self.job_id.id])],
        })
        # _inverse_scope already created a config row when job_ids was set
        # via the create above. Find it and write our payload.
        config = Config.search([
            ('job_id', '=', self.job_id.id),
            ('stage_id', '=', stage.id),
        ], limit=1)
        if not config:
            config = Config.create({
                'job_id': self.job_id.id,
                'stage_id': stage.id,
                'sequence': self.sequence,
            })
        config.write({
            'sequence': self.sequence,
            'visible': True,
            'mail_template_id': self.mail_template_id.id or False,
            'requirements': self.requirements or False,
            'test_task_description': self.test_task_description or False,
        })
        if self.link_ids:
            config.link_ids = [(5, 0, 0)] + [
                (0, 0, {
                    'label': link.label,
                    'url': link.url,
                    'sequence': link.sequence,
                })
                for link in self.link_ids
            ]
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.job',
            'res_id': self.job_id.id,
            'view_mode': 'form',
            'target': 'current',
        }


class HrJobStageCreateWizardLink(models.TransientModel):
    _name = 'hr.job.stage.create.wizard.link'
    _description = 'Resource link line in the create-stage wizard'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'hr.job.stage.create.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    label = fields.Char(required=True)
    url = fields.Char(required=True)
