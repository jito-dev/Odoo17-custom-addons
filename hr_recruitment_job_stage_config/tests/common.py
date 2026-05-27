# -*- coding: utf-8 -*-
"""Shared base class for hr_recruitment_job_stage_config tests."""
from odoo.tests.common import TransactionCase


class StageConfigTestCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Stage = cls.env['hr.recruitment.stage']
        cls.Job = cls.env['hr.job']
        cls.Applicant = cls.env['hr.applicant']
        cls.Config = cls.env['hr.job.stage.config']
        cls.MailTemplate = cls.env['mail.template']

        cls.dept = cls.env['hr.department'].create({'name': 'Engineering JSC'})

        cls.job_a = cls.Job.create({
            'name': 'Backend Engineer JSC',
            'department_id': cls.dept.id,
        })
        cls.job_b = cls.Job.create({
            'name': 'Frontend Engineer JSC',
            'department_id': cls.dept.id,
        })

    @classmethod
    def _create_stage(cls, name, sequence=10, job_ids=None, template_id=None, fold=False):
        vals = {'name': name, 'sequence': sequence, 'fold': fold}
        if job_ids:
            vals['job_ids'] = [(6, 0, [j.id for j in job_ids])]
        if template_id:
            vals['template_id'] = template_id
        return cls.Stage.create(vals)

    @classmethod
    def _create_applicant(cls, name, job, stage=None):
        # hr.applicant.name is NOT NULL (Char required=True). It is only
        # auto-populated via the form-only @api.onchange('job_id'); programmatic
        # create() must pass it explicitly. Reuse `name` for both subject and
        # partner_name so the test fixture stays single-source.
        vals = {'name': name, 'partner_name': name, 'job_id': job.id}
        if stage:
            vals['stage_id'] = stage.id
        return cls.Applicant.create(vals)

    @classmethod
    def _get_or_create_config(cls, job, stage, **vals):
        # The stage.create() override auto-materialises hr.job.stage.config
        # rows for every existing job when a global stage is born, and the
        # stage.write({'job_ids': ...}) override calls _ensure_config_rows_for_jobs
        # for every newly-added job. As a result, by the time a test grabs
        # the (job, stage) pair, the row almost always exists already, and a
        # naïve `Config.create({'job_id', 'stage_id'})` hits the unique
        # constraint hr_job_stage_config_job_stage_uniq.
        # This helper does the search-or-create dance and applies the kwargs
        # via write() so callers express intent ("set visible=False on the
        # config row for this pair") without caring whether the row was
        # auto-seeded by a hook or freshly created here.
        cfg = cls.Config.search([
            ('job_id', '=', job.id),
            ('stage_id', '=', stage.id),
        ], limit=1)
        if not cfg:
            cfg = cls.Config.create({
                'job_id': job.id,
                'stage_id': stage.id,
                **vals,
            })
        elif vals:
            cfg.write(vals)
        return cfg
