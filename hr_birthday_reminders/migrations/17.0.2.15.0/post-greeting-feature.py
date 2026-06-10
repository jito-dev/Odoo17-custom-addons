"""Migration to v17.0.2.15.0.

Employee-greeting feature: send a personal birthday email to each
today-birthday employee, log the result, surface the outcome as a chip
on the Employees views, and notify Responsibles when delivery fails.

Two idempotent responsibilities:

1. Seed ``ir.config_parameter``
   ``hr_birthday_reminders.greeting_enabled`` to ``'True'`` when the
   key is absent. The feature is meant to be on out-of-the-box; the
   Python default callable in ``res.config.settings`` already returns
   ``True`` when the param is missing, but persisting a value here
   means the settings page renders the toggle as ON visibly from the
   first save and no further reasoning about "default vs unset"
   is required at read time.

2. Warm up ``hr.employee.birthday_greeting_state`` for any employee
   whose birthday is today. The new compute field is stored, so after
   ``-u`` the column exists but holds the column-default for every
   row (False/NULL). Calling the lightweight refresh helper projects
   the latest greeting Log row (if any) onto today's birthday people
   so the chip-marker reflects state from the very first page load
   — no need to wait for the next cron tick.

Schema additions (new Selection option on ``birthday.reminder.log.interval``,
new ``greeting_status`` / ``greeting_failure_reason`` columns on the
log table, new ``birthday_greeting_state`` column on ``hr_employee``)
are applied automatically by Odoo's auto schema-sync — no ALTER TABLE
needed here.
"""

import logging

from odoo import api, fields, SUPERUSER_ID

_logger = logging.getLogger(__name__)

PARAM = 'hr_birthday_reminders.greeting_enabled'
DEFAULT_VALUE = 'True'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    ICP = env['ir.config_parameter'].sudo()
    if not ICP.get_param(PARAM):
        ICP.set_param(PARAM, DEFAULT_VALUE)
        _logger.info(
            "Birthday Reminders v17.0.2.15.0: seeded %s = %s.",
            PARAM, DEFAULT_VALUE,
        )

    try:
        today = fields.Date.context_today(env.user)
        env['hr.employee']._refresh_greeting_state_today(today)
    except Exception:
        _logger.exception(
            "Birthday Reminders v17.0.2.15.0: greeting-state warm-up "
            "failed (non-fatal — next cron tick will recover)."
        )
