# -*- coding: utf-8 -*-
{
    'name': 'HR Recruitment — Per-job Stage Configuration',
    'version': '17.0.1.0.7',
    'category': 'Human Resources/Recruitment',
    'summary': 'Through-model hr.job.stage.config for per-job stage payload (email template, sequence, visibility, requirements, links)',
    'description': """
HR Recruitment — Per-job Stage Configuration (Phase 1, PR 1b)
==============================================================

Foundation module for the stages-first recruitment redesign.

Introduces a through-model ``hr.job.stage.config`` carrying payload
on the ``(hr.job, hr.recruitment.stage)`` edge. This unblocks every
follow-up feature in the recruitment roadmap (per-job email templates,
hidden stages, per-job test-task description, call-stage booking link,
named URL resources, ...).

Key contracts:

* ``hr.recruitment.stage.scope`` Selection (``global`` / ``specific``) —
  stored, computed from ``job_ids``, with inverse for the form switcher.
* ``hr.recruitment.stage.default_get`` — pre-fills ``job_ids`` with the
  ``default_job_id`` from context (replaces the standalone
  ``hr_recruitment_stage_default_fix`` patch with a more complete
  implementation; the standalone module remains compatible).
* ``hr.applicant._read_group_stage_ids`` — single-SQL OR-domain that
  hides per-job-hidden stages while always surfacing stages currently
  hosting any applicant (R10 safety).
* ``hr.applicant._compute_stage`` — default stage for a new applicant
  excludes per-job hidden stages and respects ``config.sequence``.
* ``hr.applicant._track_template`` — fallback chain
  ``config.mail_template_id`` → ``stage.template_id`` → no mail.
* Migration is additive only — applicant.stage_id snapshot/diff guarded
  via ``pre-migrate`` and ``post-migrate`` scripts.

See ``docs/recruitment_master_plan.md`` for the full plan.
""",
    'author': 'Jito',
    'website': 'https://jito.dev',
    'depends': [
        'hr_recruitment',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_recruitment_stage_views.xml',
        'views/hr_job_stage_config_views.xml',
        'views/hr_job_views.xml',
        'wizards/hr_job_stage_create_wizard_views.xml',
        'wizards/hr_job_stage_config_hide_confirm_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_hook',
}
