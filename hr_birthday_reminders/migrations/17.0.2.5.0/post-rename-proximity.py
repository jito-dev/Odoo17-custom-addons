"""Migration to v17.0.2.5.0.

Selection keys for ``hr.employee.birthday_proximity`` are renamed with a
numeric prefix so that Odoo's alphabetical group_by sort matches the
intended urgency order:

    today      -> 1_today
    tomorrow   -> 2_tomorrow
    this_week  -> 3_this_week
    later      -> 4_later

Without the prefix the kanban groups appear as
``Later → This Week → Today → Tomorrow`` (alphabetical by key) instead
of the desired ``Today → Tomorrow → This Week → Later``.

This migration rewrites every existing ``hr_employee.birthday_proximity``
row directly in SQL so the column is consistent before the next cron
tick. The compute method now writes the new keys, so future runs stay
correct.
"""

import logging

_logger = logging.getLogger(__name__)


KEY_MAP = {
    'today':     '1_today',
    'tomorrow':  '2_tomorrow',
    'this_week': '3_this_week',
    'later':     '4_later',
}


def migrate(cr, version):
    if not version:
        return  # Fresh install — column was created with new keys already.

    for old_key, new_key in KEY_MAP.items():
        cr.execute(
            "UPDATE hr_employee SET birthday_proximity = %s "
            "WHERE birthday_proximity = %s",
            (new_key, old_key),
        )
        if cr.rowcount:
            _logger.info(
                "Birthday Reminders v17.0.2.5.0 migration: "
                "renamed %d row(s) %s -> %s.",
                cr.rowcount, old_key, new_key,
            )
