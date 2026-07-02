from odoo import models, fields, api


class MgmtSourceLine(models.Model):
    _name = 'mgmt.source.line'
    _description = 'Management Accounting Source Line'
    _order = 'date desc, id desc'
    _rec_name = 'display_name'

    source_move_line_id = fields.Many2one(
        'account.move.line',
        string='Source Journal Item',
        index=True,
        ondelete='set null',
    )
    source_move_id = fields.Many2one(
        'account.move',
        string='Source Journal Entry',
        related='source_move_line_id.move_id',
        store=True,
    )
    period_id = fields.Many2one(
        'mgmt.period',
        string='Period',
        required=True,
        index=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    # Denormalized snapshot fields
    date = fields.Date(
        string='Date',
    )
    financial_account_id = fields.Many2one(
        'account.account',
        string='Financial Account',
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Journal',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
    )
    label = fields.Char(
        string='Label',
    )
    ref = fields.Char(
        string='Reference',
    )
    debit = fields.Monetary(
        string='Debit',
        currency_field='currency_id',
    )
    credit = fields.Monetary(
        string='Credit',
        currency_field='currency_id',
    )
    balance = fields.Monetary(
        string='Balance',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
    )
    analytic_distribution = fields.Json(
        string='Analytic Distribution',
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
    )
    quantity = fields.Float(
        string='Quantity',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('processed', 'Processed'),
        ],
        string='Status',
        default='draft',
    )
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
    )

    # --- Mapping result (forward traceability) ---
    ledger_line_ids = fields.One2many(
        'mgmt.ledger.line',
        'source_line_id',
        string='Ledger Lines',
    )
    ledger_line_count = fields.Integer(
        string='Ledger Lines',
        compute='_compute_ledger_info',
    )
    mapped_mgmt_account_id = fields.Many2one(
        'mgmt.account',
        string='Mapped To',
        compute='_compute_ledger_info',
    )
    mapped_by_rule_id = fields.Many2one(
        'mgmt.mapping.rule',
        string='Classification Rule',
        compute='_compute_ledger_info',
    )

    _sql_constraints = [
        ('source_period_uniq', 'UNIQUE(source_move_line_id, period_id)',
         'Each source line can only be ingested once per period.'),
    ]

    @api.depends('ledger_line_ids', 'ledger_line_ids.mgmt_account_id', 'ledger_line_ids.mapping_rule_id')
    def _compute_ledger_info(self):
        for record in self:
            ledger_lines = record.ledger_line_ids
            record.ledger_line_count = len(ledger_lines)
            # Show the mapping-origin ledger line's account and rule
            mapping_line = ledger_lines.filtered(lambda l: l.origin_type == 'mapping')[:1]
            record.mapped_mgmt_account_id = mapping_line.mgmt_account_id if mapping_line else False
            record.mapped_by_rule_id = mapping_line.mapping_rule_id if mapping_line else False

    def _compute_display_name(self):
        for record in self:
            label = record.label or record.ref or ''
            record.display_name = f"{record.date} - {label}" if record.date else label

    def action_view_ledger_lines(self):
        """Open related ledger lines in a list view."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Ledger Lines: {self.display_name}',
            'res_model': 'mgmt.ledger.line',
            'view_mode': 'tree,form',
            'domain': [('source_line_id', '=', self.id)],
            'context': {'default_source_line_id': self.id},
        }

    def action_view_financial_entry(self):
        """Open the original financial journal entry."""
        self.ensure_one()
        if not self.source_move_id:
            return
        return {
            'type': 'ir.actions.act_window',
            'name': 'Journal Entry',
            'res_model': 'account.move',
            'res_id': self.source_move_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_assign_account(self):
        """Open the assign-account wizard for this source line."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Classify Source Line',
            'res_model': 'mgmt.assign.account.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_source_line_id': self.id,
                'default_period_id': self.period_id.id,
                'default_company_id': self.company_id.id,
            },
        }

    def action_reset_to_draft(self):
        """Delete related mapping ledger lines and reset source lines to draft."""
        for line in self:
            if line.state != 'processed':
                continue
            line.period_id._check_period_open()
            # Delete mapping ledger lines linked to this source line
            mapping_lines = line.ledger_line_ids.filtered(
                lambda l: l.origin_type == 'mapping'
            )
            if mapping_lines:
                mapping_lines.unlink()
            line.state = 'draft'
