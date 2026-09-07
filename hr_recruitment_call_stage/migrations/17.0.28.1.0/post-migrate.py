# -*- coding: utf-8 -*-
"""v17.0.28.1.0 — repair appointment types left without cover properties.

The v17.0.28.0.0 pass created a dedicated appointment type for every stage whose
Interviewer had been narrowing. It created them through the ORM — and a module's
post-migrate runs while the registry is still being built, so the fields
``website_appointment`` adds to ``appointment.type`` were not necessarily loaded
yet. Any type created in that window came out with ``cover_properties`` NULL.

Nothing complains until somebody opens that type's website page, and then it is
a 500: ``website.record_cover`` runs ``json.loads(cover_properties)`` and
``False`` is not JSON. Reported from the Appointments preview on odoo_dev.

The v17.0.28.0.0 script now copies those columns in SQL, so no new type can come
out that way. This pass repairs the ones already written — and, since the fix
costs nothing, any other type on the database missing the value for whatever
reason.

Written in SQL for the same reason the bug exists: this module does not depend
on ``website_appointment``, so the field may be absent from the model here while
the column is perfectly present on the table.
"""
import json
import logging

_logger = logging.getLogger(__name__)

# `website.cover_properties.mixin._default_cover_properties`
# (website/models/mixins.py). Kept as a literal because the mixin may not be in
# the registry at this point.
DEFAULT_COVER_PROPERTIES = json.dumps({
    "background_color_class": "o_cc3",
    "background-image": "none",
    "opacity": "0.2",
    "resize_class": "o_half_screen_height",
})


def migrate(cr, version):
    cr.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'appointment_type' "
        "AND column_name = 'cover_properties'")
    if not cr.fetchone():
        # website_appointment is not installed; there is no cover to repair.
        return

    cr.execute(
        "UPDATE appointment_type SET cover_properties = %s "
        "WHERE cover_properties IS NULL RETURNING id",
        (DEFAULT_COVER_PROPERTIES,))
    repaired = [row[0] for row in cr.fetchall()]
    if repaired:
        _logger.info(
            "hr_recruitment_call_stage: gave default cover properties to "
            "appointment type(s) %s — without them their website page raises "
            "a 500 in website.record_cover.",
            ', '.join(str(i) for i in repaired))
