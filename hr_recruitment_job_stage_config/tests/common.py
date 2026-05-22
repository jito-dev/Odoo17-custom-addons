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
        vals = {'partner_name': name, 'job_id': job.id}
        if stage:
            vals['stage_id'] = stage.id
        return cls.Applicant.create(vals)
