# -*- coding: utf-8 -*-
"""Post-migrate → 17.0.24.13.0.

``call_outcome`` moved from ``hr.applicant`` (one per candidate) to
``calendar.event`` (one per booked call), so each Call Stage keeps its own
attended / no-show verdict. This best-effort migration carries existing
applicant outcomes onto the candidate's most recent active booked call event so
historical verdicts are not lost.

Safe / conservative:
  * the old ``hr_applicant.call_outcome`` column is NOT dropped when the field
    becomes computed (Odoo leaves orphan columns), so we read it via raw SQL —
    guarded by an information_schema check in case it is already gone;
  * only ``attended`` / ``no_show`` are carried (``pending`` is the default);
  * only events that still have ``call_outcome = 'pending'`` are written, so a
    re-run never clobbers a freshly recorded verdict;
  * applicants with no booked event are skipped (nothing to attach to).
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'hr_applicant' AND column_name = 'call_outcome'
    """)
    if not cr.fetchone():
        _logger.info("17.0.24.13.0: no legacy hr_applicant.call_outcome "
                     "column; nothing to migrate.")
        return

    cr.execute("""
        UPDATE calendar_event ce
           SET call_outcome = src.call_outcome
          FROM (
                SELECT DISTINCT ON (ce2.applicant_id)
                       ce2.id AS event_id, a.call_outcome
                  FROM hr_applicant a
                  JOIN calendar_event ce2
                    ON ce2.applicant_id = a.id AND ce2.active = TRUE
                 WHERE a.call_outcome IN ('attended', 'no_show')
                 ORDER BY ce2.applicant_id, ce2.start DESC NULLS LAST
               ) src
         WHERE ce.id = src.event_id
           AND (ce.call_outcome IS NULL OR ce.call_outcome = 'pending')
        RETURNING ce.id
    """)
    migrated = [r[0] for r in cr.fetchall()]
    _logger.info(
        "17.0.24.13.0: carried legacy call_outcome onto %d booked call "
        "event(s) (ids=%s).", len(migrated), migrated)
