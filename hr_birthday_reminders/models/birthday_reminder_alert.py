from odoo import fields, models


KIND_SELECTION = [
    ('degraded', 'Degraded'),
    ('recovered', 'Recovered'),
]


class BirthdayReminderAlert(models.Model):
    """Persistent audit record for every health-watchdog alert.

    The watchdog cron (``_cron_birthday_health_watchdog`` on
    ``hr.employee``) reads the live Health Dashboard, and when the
    overall status crosses into ``danger`` (or stays there past the
    configured repeat window) emits an alert via inbox + email. Each
    such emission persists one row here so:

    1. ``message_notify`` has a stable record to anchor to (TransientModel
       ``birthday.reminder.health`` would be auto-vacuumed and break the
       Inbox link). ``mail.thread`` chatter lives on this model.
    2. Managers can open *Birthday Reminders → Alert History* and see
       when the system flagged something, what it said, and whom it
       notified — instead of digging through old mail.message rows.

    The model is append-only by design — no edit, no delete from the
    UI. Cleanup is up to Odoo's standard data-retention practices.
    """

    _name = 'birthday.reminder.alert'
    _description = 'Birthday Reminders Health Alert'
    _inherit = ['mail.thread']
    _order = 'triggered_at desc'
    _rec_name = 'triggered_at'

    triggered_at = fields.Datetime(
        string='Triggered at',
        default=fields.Datetime.now,
        readonly=True,
        required=True,
        index=True,
    )
    kind = fields.Selection(
        selection=KIND_SELECTION,
        string='Kind',
        required=True,
        readonly=True,
        help="``degraded`` when the dashboard turned red; ``recovered`` "
             "when it came back to green.",
    )
    overall_status = fields.Char(
        string='Overall status (snapshot)',
        readonly=True,
        help="Snapshot of birthday.reminder.health.overall_status at the "
             "moment of alert emission. Frozen — does not change as the "
             "underlying health does.",
    )
    overall_message = fields.Text(
        string='Summary (snapshot)',
        readonly=True,
    )
    notified_partner_ids = fields.Many2many(
        comodel_name='res.partner',
        string='Notified partners',
        readonly=True,
        help="The admin + manager partners that received this alert "
             "via Inbox + email.",
    )
