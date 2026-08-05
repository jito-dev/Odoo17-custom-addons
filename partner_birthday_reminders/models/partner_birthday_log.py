from odoo import fields, models

from .constants import (
    INTERVAL_1_DAY,
    INTERVAL_7_DAYS,
    INTERVAL_ON_DAY,
)


class PartnerBirthdayLog(models.Model):
    """Idempotency log + audit trail for contact birthday reminders.

    One row per ``(partner, occurrence date, interval, account manager)``
    quadruple that has already been notified. The cron consults this
    table before emitting anything, so re-running it — manually, twice
    the same day, or in parallel — never produces duplicate activities,
    inbox notifications or emails. The UNIQUE constraint is the hard
    guarantee; the pre-check is only there to avoid useless work.

    A dedicated table (rather than searching ``mail.activity`` or the
    chatter) is deliberate: activities are user-deletable and messages
    can be removed, so neither can answer "did we already notify?".
    It doubles as the audit trail an Account Manager can open to see
    what the system told them and when.
    """

    _name = 'partner.birthday.log'
    _description = 'Contact Birthday Reminder Log'
    _order = 'notified_at desc'
    _rec_name = 'partner_id'

    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Contact',
        required=True,
        index=True,
        ondelete='cascade',
    )
    user_id = fields.Many2one(
        comodel_name='res.users',
        string='Account Manager',
        required=True,
        index=True,
        ondelete='cascade',
        help="The Account Manager who received this reminder — i.e. the "
             "contact's user_id at the moment the reminder was emitted. "
             "Kept even if the contact is later reassigned, so the log "
             "stays an accurate record of who was actually told.",
    )
    birthday_date = fields.Date(
        string='Birthday Occurrence',
        required=True,
        index=True,
        help="The calendar date this reminder is anchored to — this "
             "year's occurrence of the contact's birthday.",
    )
    interval = fields.Selection(
        selection=[
            (INTERVAL_7_DAYS, '7 days before'),
            (INTERVAL_1_DAY, '1 day before'),
            (INTERVAL_ON_DAY, 'On birthday'),
        ],
        string='Interval',
        required=True,
    )
    notified_at = fields.Datetime(
        string='Notified At',
        default=fields.Datetime.now,
        readonly=True,
    )

    _sql_constraints = [
        (
            'uniq_partner_date_interval_user',
            'unique(partner_id, birthday_date, interval, user_id)',
            'A birthday reminder for this contact, date, interval and '
            'account manager already exists.',
        ),
    ]
