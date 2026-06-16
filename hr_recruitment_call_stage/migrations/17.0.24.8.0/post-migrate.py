# -*- coding: utf-8 -*-
"""Post-migrate → 17.0.24.8.0.

Backfill the per-job email override (``mail_template_id``) on every Call
Stage config row that still has none, so the "Email Template (per-job
override)" field is never shown empty for a Call Stage.

Why this is needed
------------------
The runtime send path resolves the effective template as
``mail_template_id`` first, then the shipped call-invite as a fallback (see
``hr.job.stage.config._call_stage_effective_template``). Newer rows get the
override auto-filled the moment the Call Stage is enabled
(create / write / onchange), but rows enabled *before* that auto-fill landed
keep an empty override and rely silently on the fallback. To the recruiter
the field then looks empty even though invites send fine.

This migration makes that implicit fallback explicit: it copies the shipped
``mail_template_call_invite_generic`` into the empty overrides. The effective
template (and therefore the email that goes out) is unchanged — override and
fallback are the same record — so this is purely a visibility fix.

Idempotent and conservative:
  * only ``is_call_stage = TRUE`` rows;
  * only rows where ``mail_template_id IS NULL`` — an explicit recruiter
    pick is never overwritten;
  * no-op when the shipped template is absent (mid-install / uninstall).
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        SELECT res_id FROM ir_model_data
         WHERE module = 'hr_recruitment_call_stage'
           AND name   = 'mail_template_call_invite_generic'
           AND model  = 'mail.template'
         LIMIT 1
        """
    )
    row = cr.fetchone()
    if not row:
        _logger.warning(
            "hr_recruitment_call_stage 17.0.24.8.0: shipped call-invite "
            "template not found; skipped per-job override backfill.")
        return
    template_id = row[0]
    cr.execute(
        """
        UPDATE hr_job_stage_config
           SET mail_template_id = %s
         WHERE is_call_stage = TRUE
           AND mail_template_id IS NULL
        RETURNING id
        """,
        (template_id,),
    )
    filled = [r[0] for r in cr.fetchall()]
    _logger.info(
        "hr_recruitment_call_stage 17.0.24.8.0: backfilled per-job email "
        "override with shipped call-invite (id=%s) on %d Call Stage config "
        "row(s) (ids=%s).",
        template_id, len(filled), filled,
    )
