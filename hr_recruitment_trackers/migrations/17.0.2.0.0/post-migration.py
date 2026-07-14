# -*- coding: utf-8 -*-
"""Back-fill `applicant_origin` ("Candidate Source") for existing applicants.

This runs in **raw SQL** on purpose. When a brand-new stored computed field is
added, Odoo back-fills it by running the compute — but that happens *during*
module loading, where the registry may still be incomplete depending on module
load order. Specifically, `hr_djinni`'s `djinni_ref` field can be absent from the
ORM registry at that moment (trackers loaded before hr_djinni), so the compute
classifies every Djinni candidate as "manual".

The physical `djinni_ref` *column* exists regardless of load order, so we
reclassify straight from the columns here, after the (possibly wrong) auto
back-fill. Pure SQL, idempotent, and independent of which module loaded first.
"""


def migrate(cr, version):
    # Came through a tracking link.
    cr.execute("""
        UPDATE hr_applicant SET applicant_origin = 'tracking_link'
        WHERE tracker_id IS NOT NULL
    """)

    # Imported by the Djinni integration — only if hr_djinni contributed its
    # column (it is a soft dependency; trackers must work without it).
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'hr_applicant' AND column_name = 'djinni_ref'
    """)
    has_djinni = bool(cr.fetchone())
    if has_djinni:
        cr.execute("""
            UPDATE hr_applicant SET applicant_origin = 'djinni'
            WHERE tracker_id IS NULL AND djinni_ref IS NOT NULL
        """)
        cr.execute("""
            UPDATE hr_applicant SET applicant_origin = 'manual'
            WHERE tracker_id IS NULL AND djinni_ref IS NULL
        """)
    else:
        cr.execute("""
            UPDATE hr_applicant SET applicant_origin = 'manual'
            WHERE tracker_id IS NULL
        """)
