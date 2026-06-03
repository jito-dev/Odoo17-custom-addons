# -*- coding: utf-8 -*-
"""Pre-migrate for 17.0.1.0.10 — clean broken mail_template_id FKs.

PR 2.5 introduces ``@api.constrains('mail_template_id')`` on
``hr.job.stage.config`` requiring the referenced ``mail.template`` to
have ``model_id`` set to ``hr.applicant``. On production databases
created before the constraint, a recruiter may have picked a template
without a model (or with a foreign model) via the legacy "Create and
edit" inline action. That broken FK is the root cause of the
``KeyError: False`` crash at ``mail/models/mail_template.py:321``.

This script NULLs out those broken references BEFORE the constraint
loads, so the module upgrade does not abort. Affected configs are
logged to ``ir.logging`` so admins can review and re-pick a valid
template via the popup form.

Additive only: never deletes ``mail.template`` rows or modifies
applicants/stages/jobs.
"""


def migrate(cr, version):
    cr.execute(
        """
        SELECT c.id, c.job_id, c.stage_id, c.mail_template_id,
               t.model_id, t.model
        FROM hr_job_stage_config c
        LEFT JOIN mail_template t ON t.id = c.mail_template_id
        WHERE c.mail_template_id IS NOT NULL
          AND (t.id IS NULL OR t.model_id IS NULL OR t.model != 'hr.applicant')
        """
    )
    broken = cr.fetchall()
    if not broken:
        return

    config_ids = [row[0] for row in broken]
    cr.execute(
        "UPDATE hr_job_stage_config SET mail_template_id = NULL WHERE id = ANY(%s)",
        (config_ids,),
    )

    for config_id, job_id, stage_id, tmpl_id, model_id, model in broken:
        message = (
            f"PR 2.5 pre-migrate: cleared mail_template_id={tmpl_id} "
            f"(model_id={model_id!r}, model={model!r}) from "
            f"hr_job_stage_config id={config_id} (job_id={job_id}, "
            f"stage_id={stage_id}). Re-pick a valid template via the "
            "stage config popup."
        )
        cr.execute(
            """
            INSERT INTO ir_logging
                (create_date, create_uid, name, type, level, message,
                 path, func, line)
            VALUES
                (NOW() AT TIME ZONE 'UTC', 1,
                 'hr_recruitment_job_stage_config.pre_migrate',
                 'server', 'WARNING', %s,
                 'migrations/17.0.1.0.10/pre-migrate.py', 'migrate', 0)
            """,
            (message,),
        )
