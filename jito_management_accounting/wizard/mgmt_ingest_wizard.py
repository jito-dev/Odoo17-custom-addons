from odoo import models, fields, api
from odoo.exceptions import UserError


class MgmtIngestWizard(models.TransientModel):
    _name = 'mgmt.ingest.wizard'
    _description = 'Management Accounting Ingestion Wizard'

    period_id = fields.Many2one(
        'mgmt.period',
        string='Period',
        required=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )

    # --- Status filters ---
    filter_posted = fields.Boolean(
        string='Posted (Validated)',
        default=True,
        help='Only ingest entries from posted/validated journal entries.',
    )
    filter_reconciled = fields.Boolean(
        string='Reconciled',
        default=False,
        help='Only ingest fully reconciled journal items.',
    )

    # --- Tier 1: High-value filters ---
    filter_journal_ids = fields.Many2many(
        'account.journal',
        string='Journals',
        help='Only ingest lines from these journals. Leave empty to include all.',
    )
    filter_account_ids = fields.Many2many(
        'account.account',
        string='Financial Accounts',
        help='Only ingest lines from these GL accounts. Leave empty to include all.',
    )
    filter_entry_type = fields.Selection(
        selection=[
            ('all', 'All Entry Types'),
            ('invoices_bills', 'Invoices & Bills'),
            ('invoices_only', 'Customer Invoices'),
            ('bills_only', 'Vendor Bills'),
            ('entries_only', 'Journal Entries'),
            ('receipts_only', 'Receipts (Payments)'),
        ],
        string='Entry Type',
        default='all',
        required=True,
        help='Filter by journal entry type.',
    )

    # --- Tier 2: Targeted filters ---
    filter_partner_ids = fields.Many2many(
        'res.partner',
        string='Partners',
        help='Only ingest lines linked to these partners. Leave empty to include all.',
    )
    filter_analytic_account_ids = fields.Many2many(
        'account.analytic.account',
        string='Analytic Accounts',
        help='Only ingest lines tagged with these analytic accounts. Leave empty to include all.',
    )
    filter_exclude_zero = fields.Boolean(
        string='Exclude Zero-Balance Lines',
        default=False,
        help='Skip journal items where debit and credit are both zero.',
    )

    # Map entry type selection to move_type values
    ENTRY_TYPE_MAP = {
        'invoices_bills': [
            'out_invoice', 'out_refund', 'in_invoice', 'in_refund',
        ],
        'invoices_only': ['out_invoice', 'out_refund'],
        'bills_only': ['in_invoice', 'in_refund'],
        'entries_only': ['entry'],
        'receipts_only': ['out_receipt', 'in_receipt'],
    }

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        config = self.env['mgmt.config']._get_singleton()
        res['filter_posted'] = config.auto_ingest_posted_only
        res['filter_reconciled'] = config.auto_ingest_reconciled_only
        if self._context.get('active_model') == 'mgmt.period':
            res['period_id'] = self._context.get('active_id')
        return res

    def _build_domain(self, period):
        """Build the search domain from all wizard filters."""
        domain = [
            ('company_id', '=', self.company_id.id),
            ('date', '>=', period.date_start),
            ('date', '<=', period.date_end),
        ]

        # Status filters
        if self.filter_posted:
            domain.append(('parent_state', '=', 'posted'))
        if self.filter_reconciled:
            domain.append(('reconciled', '=', True))

        # Journal filter
        if self.filter_journal_ids:
            domain.append(('journal_id', 'in', self.filter_journal_ids.ids))

        # Financial account filter
        if self.filter_account_ids:
            domain.append(('account_id', 'in', self.filter_account_ids.ids))

        # Entry type filter
        if self.filter_entry_type and self.filter_entry_type != 'all':
            move_types = self.ENTRY_TYPE_MAP.get(self.filter_entry_type, [])
            if move_types:
                domain.append(('move_id.move_type', 'in', move_types))

        # Partner filter
        if self.filter_partner_ids:
            domain.append(('partner_id', 'in', self.filter_partner_ids.ids))

        # Exclude zero-balance lines
        if self.filter_exclude_zero:
            domain.append('|')
            domain.append(('debit', '!=', 0))
            domain.append(('credit', '!=', 0))

        # Exclude already ingested lines
        existing_ids = self.env['mgmt.source.line'].search([
            ('period_id', '=', period.id),
        ]).mapped('source_move_line_id').ids
        if existing_ids:
            domain.append(('id', 'not in', existing_ids))

        return domain

    def _filter_by_analytic(self, move_lines):
        """Post-filter move lines by analytic account (JSON field)."""
        if not self.filter_analytic_account_ids:
            return move_lines
        target_ids = set(self.filter_analytic_account_ids.ids)
        filtered = self.env['account.move.line']
        for ml in move_lines:
            if not ml.analytic_distribution:
                continue
            # analytic_distribution keys are comma-separated account IDs
            for key in ml.analytic_distribution:
                line_ids = {int(x) for x in key.split(',')}
                if line_ids & target_ids:
                    filtered |= ml
                    break
        return filtered

    def action_ingest(self):
        self.ensure_one()
        period = self.period_id
        period._check_period_open()

        domain = self._build_domain(period)
        move_lines = self.env['account.move.line'].search(domain)

        # Post-filter: analytic accounts (JSON field, can't filter via domain)
        move_lines = self._filter_by_analytic(move_lines)

        if not move_lines:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Ingestion Complete',
                    'message': 'No new source lines to ingest.',
                    'type': 'warning',
                    'sticky': False,
                },
            }

        vals_list = []
        for ml in move_lines:
            vals_list.append({
                'source_move_line_id': ml.id,
                'period_id': period.id,
                'company_id': self.company_id.id,
                'date': ml.date,
                'financial_account_id': ml.account_id.id,
                'journal_id': ml.journal_id.id,
                'partner_id': ml.partner_id.id if ml.partner_id else False,
                'label': ml.name,
                'ref': ml.move_id.ref,
                'debit': ml.debit,
                'credit': ml.credit,
                'balance': ml.balance,
                'currency_id': ml.company_currency_id.id,
                'analytic_distribution': ml.analytic_distribution,
                'product_id': ml.product_id.id if ml.product_id else False,
                'quantity': ml.quantity,
                'state': 'draft',
            })

        self.env['mgmt.source.line'].create(vals_list)

        # Build filter summary
        filters = []
        if self.filter_posted:
            filters.append('posted')
        if self.filter_reconciled:
            filters.append('reconciled')
        if self.filter_journal_ids:
            filters.append(f"journals: {', '.join(self.filter_journal_ids.mapped('name'))}")
        if self.filter_account_ids:
            filters.append(f"{len(self.filter_account_ids)} accounts")
        if self.filter_entry_type != 'all':
            filters.append(dict(self._fields['filter_entry_type'].selection).get(self.filter_entry_type, ''))
        if self.filter_partner_ids:
            filters.append(f"{len(self.filter_partner_ids)} partners")
        if self.filter_analytic_account_ids:
            filters.append(f"{len(self.filter_analytic_account_ids)} analytic accts")
        if self.filter_exclude_zero:
            filters.append('excl. zero')
        filter_str = f" ({', '.join(filters)})" if filters else ""

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Ingestion Complete',
                'message': f'{len(vals_list)} source lines ingested{filter_str} for period {period.name}.',
                'type': 'success',
                'sticky': False,
            },
        }
