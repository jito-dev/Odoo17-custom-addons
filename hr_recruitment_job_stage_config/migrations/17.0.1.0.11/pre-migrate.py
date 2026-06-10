# -*- coding: utf-8 -*-
"""Pre-migrate for 17.0.1.0.11 — backfill orphan (job, stage) config rows.

v17.0.1.0.11 replaces the stock hr.applicant.stage_id static domain
(['|', ('job_ids', '=', False), ('job_ids', '=', job_id)]) with a
config-driven one referencing the new computed M2M allowed_stage_ids.
The OR-branch handling specific stages requires that for every
(hr_job_hr_recruitment_stage_rel) row a matching hr_job_stage_config
row exists. Without this backfill, legacy specific stages whose config
row was never created (partial post_init_hook, direct SQL inserts,
pre-1.0.1 data) would silently disappear from the dropdown / statusbar
/ tree views for their owning job — a regression.

Additive only: never modifies existing rows, never touches
hr.applicant.stage_id (R2 guarantee), never deletes anything.

Spec: docs/migration_17_0_1_0_11_instruction.md.
"""


def migrate(cr, version):
    # Tolerate fresh installs where the table may not yet exist (Odoo
    # calls pre-migrate before module install in some flows).
    cr.execute(
        """
        SELECT to_regclass('public.hr_job_stage_config'),
               to_regclass('public.hr_job_hr_recruitment_stage_rel')
        """
    )
    config_tbl, rel_tbl = cr.fetchone()
    if not config_tbl or not rel_tbl:
        return

    # §3.1 — find orphan (job, stage) pairs (in M2M rel, not in config).
    cr.execute(
        """
        SELECT rel.hr_job_id, rel.hr_recruitment_stage_id
        FROM   hr_job_hr_recruitment_stage_rel rel
        LEFT JOIN hr_job_stage_config c
               ON c.job_id   = rel.hr_job_id
              AND c.stage_id = rel.hr_recruitment_stage_id
        WHERE  c.id IS NULL
        """
    )
    orphans = cr.fetchall()
    if not orphans:
        return

    # §3.2 — fetch sequence for each orphan stage.
    stage_ids = sorted({stage_id for _job_id, stage_id in orphans})
    cr.execute(
        "SELECT id, sequence FROM hr_recruitment_stage WHERE id = ANY(%s)",
        (stage_ids,),
    )
    seq_by_stage = dict(cr.fetchall())

    # §3.3 — idempotent INSERT (UNIQUE(job_id, stage_id) since 1.0.0).
    rows = [
        (job_id, stage_id, seq_by_stage.get(stage_id, 10))
        for job_id, stage_id in orphans
    ]
    cr.executemany(
        """
        INSERT INTO hr_job_stage_config
            (job_id, stage_id, sequence, visible,
             create_uid, create_date, write_uid, write_date)
        VALUES
            (%s, %s, %s, TRUE,
             1, NOW() AT TIME ZONE 'UTC', 1, NOW() AT TIME ZONE 'UTC')
        ON CONFLICT (job_id, stage_id) DO NOTHING
        """,
        rows,
    )

    # §3.4 — log the backfill so DevOps can post-mortem what was created.
    sample = orphans[:100]
    message = (
        "v17.0.1.0.11 pre-migrate: backfilled %d orphan hr_job_stage_config "
        "rows for the new allowed_stage_ids domain. Each row was created with "
        "visible=TRUE (preserves stock visibility semantics from the legacy "
        "job_ids M2M domain). (job_id, stage_id) sample (first 100): %r%s"
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
             'hr_recruitment_job_stage_config.pre_migrate',
             'server', 'INFO', %s,
             'migrations/17.0.1.0.11/pre-migrate.py', 'migrate', 0)
        """,
        (message,),
    )

    # §3.5 — verify the invariant. Re-check; raise if not clean (fail-fast
    # rather than letting the new domain hide data).
    cr.execute(
        """
        SELECT COUNT(*)
        FROM   hr_job_hr_recruitment_stage_rel rel
        LEFT JOIN hr_job_stage_config c
               ON c.job_id   = rel.hr_job_id
              AND c.stage_id = rel.hr_recruitment_stage_id
        WHERE  c.id IS NULL
        """
    )
    remaining = cr.fetchone()[0]
    if remaining:
        raise RuntimeError(
            "v17.0.1.0.11 pre-migrate: invariant broken — %d orphan "
            "(job, stage) pairs remain in hr_job_hr_recruitment_stage_rel "
            "after backfill. Aborting upgrade to avoid hiding specific "
            "stages via the new allowed_stage_ids domain. Investigate "
            "concurrent writes to hr_job_hr_recruitment_stage_rel during "
            "migration." % remaining
        )
