from odoo import api, fields, models, _


class UsaAccountMap(models.Model):
    """Injection rule: maps an Upwork (transaction_type, accounting_subtype) to the
    GL account used as the *counterpart* when a transaction is injected as a bank
    statement line on the Upwork Wallet journal.

    Lookup order (see usa.settings._get_account_for_transaction):
        exact (type, subtype) → (type, blank subtype) wildcard → settings fallback.
    """

    _name = 'usa.account.map'
    _description = 'Upwork Subtype → GL Account Injection Rule'
    _order = 'sequence, transaction_type, accounting_subtype'
    _rec_name = 'label'

    config_id = fields.Many2one(
        'usa.settings', string='Configuration',
        ondelete='cascade', index=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company, index=True,
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    label = fields.Char(string='Description', help='Human label, e.g. "Hourly revenue".')

    transaction_type = fields.Char(
        string='Upwork Type', required=True, index=True,
        help="Upwork transaction 'type', e.g. APInvoice, APAdjustment, ARInvoice, "
             "APPayment, ARPayment.",
    )
    accounting_subtype = fields.Char(
        string='Upwork Subtype', index=True,
        help="Upwork 'accountingSubtype', e.g. Hourly, Fixed Price, Service Fee. "
             "Leave blank to act as a wildcard fallback for the whole type.",
    )

    account_id = fields.Many2one(
        'account.account', string='Counterpart GL Account', required=True,
        domain="[('company_id', '=', company_id), ('deprecated', '=', False)]",
        help='Account posted as the counterpart of the injected bank statement line.',
    )
    tax_id = fields.Many2one(
        'account.tax', string='Tax (optional)',
        domain="[('company_id', '=', company_id)]",
        help='Reserved for a future tax-coded flow. Currently stored but NOT applied '
             'to the injected line.',
    )
    posting_mode = fields.Selection(
        selection=[
            ('gl', 'Direct GL (counterpart)'),
            ('customer_invoice', 'Customer Invoice (out_invoice)'),
            ('customer_refund', 'Customer Credit Note (out_refund)'),
            ('vendor_bill', 'Vendor Bill (in_invoice)'),
            ('vendor_refund', 'Vendor Credit Note (in_refund)'),
        ],
        string='Posting Mode', default='gl', required=True,
        help="gl: inject the bank line straight to the counterpart GL account. "
             "customer_invoice / vendor_bill: inject the bank line to suspense and "
             "recognise P&L via a generated document reconciled against the line "
             "(prevents double-counting).",
    )

    _sql_constraints = [
        ('usa_map_key_uniq',
         'unique(company_id, transaction_type, accounting_subtype)',
         'A mapping rule for this Type / Subtype already exists for this company.'),
    ]

    @api.depends('label', 'transaction_type', 'accounting_subtype')
    def _compute_display_name(self):
        for rec in self:
            key = rec.transaction_type or ''
            if rec.accounting_subtype:
                key = '%s / %s' % (key, rec.accounting_subtype)
            rec.display_name = rec.label or key or _('Injection Rule')
