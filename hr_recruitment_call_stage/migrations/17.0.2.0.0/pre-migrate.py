# -*- coding: utf-8 -*-
"""Pre-migrate for 17.0.1.2.0 → 17.0.2.0.0 (Etap 2: native swap).

Move the (applicant ↔ appointment_invite) linkage from our join table
``hr_applicant_booking_invite`` onto the native field
``appointment_invite.applicant_id`` shipped by
``appointment_hr_recruitment``.

Strategy:
1. Copy ``applicant_id`` from each link row to its referenced
   ``appointment_invite`` row, ONLY if the native field is currently NULL
   (preserve any value the native UI may have set).
2. Rename the old join table to ``..._etap2_backup``. We do NOT drop it
   here — post-migrate cleans up `ir.model` (which would otherwise
   recreate the table on next install). The backup remains in the DB
   for one release cycle so a rollback can restore data.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # ---- 0. Skip if the old table doesn't exist (fresh install path)
    cr.execute("""
        SELECT 1 FROM information_schema.tables
         WHERE table_name = 'hr_applicant_booking_invite'
    """)
    if not cr.fetchone():
        _logger.info(
            "hr_recruitment_call_stage 17.0.2.0.0: no legacy join table "
            "— nothing to migrate.")
        return

    # ---- 1. Copy applicant_id to native appointment_invite -----------
    cr.execute("""
        UPDATE appointment_invite ai
           SET applicant_id = link.applicant_id
          FROM hr_applicant_booking_invite link
         WHERE link.invite_id = ai.id
           AND ai.applicant_id IS NULL
    """)
    moved = cr.rowcount
    _logger.info(
        "hr_recruitment_call_stage 17.0.2.0.0: copied applicant_id onto "
        "%d appointment_invite rows from legacy join table.", moved,
    )

    # ---- 2. Rename old table to backup (rollback safety) -------------
    # Drop a stale backup if one happens to exist (e.g. a previous
    # aborted migration run) — keep the most recent attempt only.
    cr.execute("""
        DROP TABLE IF EXISTS hr_applicant_booking_invite_etap2_backup
    """)
    cr.execute("""
        ALTER TABLE hr_applicant_booking_invite
            RENAME TO hr_applicant_booking_invite_etap2_backup
    """)
    _logger.info(
        "hr_recruitment_call_stage 17.0.2.0.0: legacy table renamed to "
        "hr_applicant_booking_invite_etap2_backup. Drop manually after "
        "verifying the next release is stable.",
    )
