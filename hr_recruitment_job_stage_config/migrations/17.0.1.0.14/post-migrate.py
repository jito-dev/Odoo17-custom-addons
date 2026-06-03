# -*- coding: utf-8 -*-
"""Post-migrate for 17.0.1.0.14 — backfill orphan (job, global_stage) config rows.

Symptom this fixes: a global stage that exists in the database but has no
hr.job.stage.config row on a given job. Such a stage appears in that
job's kanban (the _visible_stages_domain rule treats globals as visible
unless explicitly hidden via a config row with visible=False) but is
absent from the Stages tab in the job form (which lists stage_config_ids).

Two production paths could create this state:
  1. v17.0.1.0.13 and earlier: hr.recruitment.stage._inverse_scope deleted
     auto-rows when a stage was flipped from scope='specific' to 'global'.
     Existing jobs were left without a row for that stage. v17.0.1.0.14
     fixes the inverse to preserve rows AND create rows for other jobs.
  2. SQL-level inserts / restored backups / interrupted earlier migrations
     that bypassed the create() override.

This migration is the one-shot backfill that establishes the invariant on
existing databases. The runtime path is fixed in hr_recruitment_stage.py.

Additive only: never modifies existing rows, never touches
hr.applicant.stage_id (R2 guarantee), never deletes anything. Idempotent
via the UNIQUE(job_id, stage_id) constraint and ON CONFLICT DO NOTHING.
"""


def migrate(cr, version):
    # Tolerate fresh installs where the table may not yet exist.
    cr.execute(
        """
        SELECT to_regclass('public.hr_job_stage_config'),
               to_regclass('public.hr_job_hr_recruitment_stage_rel'),
               to_regclass('public.hr_recruitment_stage'),
               to_regclass('public.hr_job')
        """
    )
    config_tbl, rel_tbl, stage_tbl, job_tbl = cr.fetchone()
    if not all((config_tbl, rel_tbl, stage_tbl, job_tbl)):
        return

    # Find every (job, global_stage) pair without a config row.
    # A "global" stage is one with no entries in hr_job_hr_recruitment_stage_rel.
    cr.execute(
        """
        SELECT j.id AS job_id,
               s.id AS stage_id,
               s.sequence AS sequence,
               COALESCE(s.default_visible_in_new_jobs, FALSE) AS visible
        FROM   hr_job j
        CROSS JOIN hr_recruitment_stage s
        WHERE  NOT EXISTS (
                   SELECT 1 FROM hr_job_hr_recruitment_stage_rel rel
                   WHERE rel.hr_recruitment_stage_id = s.id
               )
          AND  NOT EXISTS (
                   SELECT 1 FROM hr_job_stage_config c
                   WHERE c.job_id = j.id AND c.stage_id = s.id
               )
        """
    )
    orphans = cr.fetchall()
    if not orphans:
        return

    cr.executemany(
        """
        INSERT INTO hr_job_stage_config
            (job_id, stage_id, sequence, visible,
             create_uid, create_date, write_uid, write_date)
        VALUES
            (%s, %s, %s, %s,
             1, NOW() AT TIME ZONE 'UTC', 1, NOW() AT TIME ZONE 'UTC')
        ON CONFLICT (job_id, stage_id) DO NOTHING
        """,
        orphans,
    )

    sample = orphans[:100]
    message = (
        "v17.0.1.0.14 post-migrate: backfilled %d orphan hr_job_stage_config "
        "rows for (job, global_stage) pairs missing from the Stages tab. "
        "visible defaulted to stage.default_visible_in_new_jobs. "
        "(job_id, stage_id, sequence, visible) sample (first 100): %r%s"
    ) % (
        len(orphans),
        sample,
        " ...truncated" if len(orphans) > 100 else "",
    )
    cr.execute(
        """
        INSERT INTO ir_logging
            (create_date, create_uid, name, type, level, message,
             path, func, line)
        VALUES
            (NOW() AT TIME ZONE 'UTC', 1,
             'hr_recruitment_job_stage_config.post_migrate',
             'server', 'INFO', %s,
             'migrations/17.0.1.0.14/post-migrate.py', 'migrate', 0)
        """,
        (message,),
    )

    # Verify the invariant. Re-check; raise if not clean.
    cr.execute(
        """
        SELECT COUNT(*)
        FROM   hr_job j
        CROSS JOIN hr_recruitment_stage s
        WHERE  NOT EXISTS (
                   SELECT 1 FROM hr_job_hr_recruitment_stage_rel rel
                   WHERE rel.hr_recruitment_stage_id = s.id
               )
          AND  NOT EXISTS (
                   SELECT 1 FROM hr_job_stage_config c
                   WHERE c.job_id = j.id AND c.stage_id = s.id
               )
        """
    )
    remaining = cr.fetchone()[0]
    if remaining:
        raise RuntimeError(
            "v17.0.1.0.14 post-migrate: invariant broken — %d (job, "
            "global_stage) pairs remain without a config row after backfill. "
            "Investigate concurrent writes during migration." % remaining
        )
