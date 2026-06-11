# Copyright © 2024 Garazd Creation (https://garazd.biz)
# License OPL-1 (https://www.odoo.com/documentation/17.0/legal/licenses.html).

from odoo import api, fields, models


class DjinniSyncLog(models.Model):
    _name = 'djinni.sync.log'
    _description = 'Djinni Applicant Sync Log'
    _order = 'date_start desc'
    _rec_name = 'display_name'

    account_id = fields.Many2one(comodel_name='djinni.account', ondelete='cascade')
    date_start = fields.Datetime(required=True)
    date_end = fields.Datetime()
    state = fields.Selection(
        selection=[
            ('success', 'Success'),
            ('partial', 'Partial'),
            ('error', 'Error'),
        ],
        default='success',
        required=True,
    )
    job_count = fields.Integer(string='Vacancies')
    new_count = fields.Integer(string='New')
    updated_count = fields.Integer(string='Updated')
    skipped_count = fields.Integer(string='Skipped')
    error_count = fields.Integer(string='Errors')
    note = fields.Text(help='Per-vacancy errors and warnings (e.g. truncation, API failures).')
    trigger = fields.Selection(
        selection=[('cron', 'Scheduled'), ('manual', 'Manual')],
        default='cron',
    )

    @api.depends('date_start', 'state', 'new_count', 'updated_count')
    def _compute_display_name(self):
        for log in self:
            log.display_name = '%s — %s (+%s/~%s)' % (
                fields.Datetime.to_string(log.date_start) or '',
                dict(self._fields['state'].selection).get(log.state, log.state),
                log.new_count,
                log.updated_count,
            )
