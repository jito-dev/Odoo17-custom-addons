from odoo import models, fields, api


class MgmtConfig(models.Model):
    _name = 'mgmt.config'
    _description = 'Management Accounting Configuration'

    lock_field = fields.Char(
        default='global',
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    auto_ingest_posted_only = fields.Boolean(
        string='Posted Only',
        default=True,
        help='When enabled, only posted (validated) journal entries are ingested.',
    )
    auto_ingest_reconciled_only = fields.Boolean(
        string='Reconciled Only',
        default=False,
        help='When enabled, only fully reconciled journal items are ingested.',
    )
    default_currency_id = fields.Many2one(
        'res.currency',
        string='Default Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    default_receivable_account_id = fields.Many2one(
        'mgmt.account',
        string='Default Receivable Account',
        help='Default management account for receivable journal entries.',
    )
    default_payable_account_id = fields.Many2one(
        'mgmt.account',
        string='Default Payable Account',
        help='Default management account for payable journal entries.',
    )

    _sql_constraints = [
        ('singleton', 'UNIQUE(lock_field)',
         'Only one management accounting configuration record is allowed.'),
    ]

    @api.model
    def _get_singleton(self):
        """Retrieve or create the singleton configuration record."""
        config = self.search([], limit=1)
        if not config:
            config = self.create({})
        return config

    @api.model
    def action_open_settings(self):
        """Open the singleton settings record (create if missing)."""
        config = self._get_singleton()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Settings',
            'res_model': 'mgmt.config',
            'res_id': config.id,
            'view_mode': 'form',
            'target': 'inline',
        }
