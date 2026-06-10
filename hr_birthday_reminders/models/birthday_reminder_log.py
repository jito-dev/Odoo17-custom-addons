from odoo import fields, models


class BirthdayReminderLog(models.Model):
    """Idempotency log for birthday reminders.

    A row is written for every (employee, occurrence date, interval, user)
    quadruple for which a notification has already been emitted. The cron
    consults this table before doing anything, so re-running the cron — or
    running it more than once on the same day — never produces duplicate
    activities, chatter messages or emails.

    The log is the single source of truth across all three notification
    channels (mail.activity, message_post, mail.template). Activities are
    user-deletable and chatter messages can be removed, so we cannot rely
    on either of them to answer "did we already notify for this?". A
    dedicated table also gives us a cheap audit trail per Responsible.
    """

    _name = 'birthday.reminder.log'
    _description = 'Birthday Reminder Log'
    _order = 'notified_at desc'
    _rec_name = 'employee_id'

    employee_id = fields.Many2one(
        comodel_name='hr.employee',
        string='Employee',
        required=True,
        index=True,
        ondelete='cascade',
    )
    user_id = fields.Many2one(
        comodel_name='res.users',
        string='Responsible',
        index=True,
        ondelete='cascade',
        help="The Responsible who received this notification. Empty for "
             "rows created before per-user subscriptions existed.",
    )
    birthday_date = fields.Date(
        string='Birthday Occurrence',
        required=True,
        index=True,
        help="The actual calendar date this reminder is anchored to "
             "(this year's occurrence of the employee's birthday).",
    )
    interval = fields.Selection(
        selection=[
            ('7_days', '7 days before'),
            ('1_day', '1 day before'),
            ('on_day', 'On birthday'),
            ('greeting', 'Greeting to employee'),
        ],
        string='Interval',
        required=True,
    )
    notified_at = fields.Datetime(
        string='Notified At',
        default=fields.Datetime.now,
        readonly=True,
    )
    # The two fields below are only populated for rows with
    # interval='greeting'. NULL on every other row.
    greeting_status = fields.Selection(
        selection=[
            ('sent', 'Sent'),
            ('failed', 'Failed'),
        ],
        string='Greeting Status',
        help="Outcome of the auto-greeting email sent to the employee. "
             "Empty on non-greeting rows.",
    )
    greeting_failure_reason = fields.Char(
        string='Greeting Failure Reason',
        help="Machine-readable code when greeting_status='failed' "
             "('no_email' or 'send_error'). Empty otherwise.",
    )

    _sql_constraints = [
        (
            'uniq_employee_date_interval_user',
            'unique(employee_id, birthday_date, interval, user_id)',
            'A birthday reminder for this employee, date, interval and '
            'responsible already exists.',
        ),
    ]
