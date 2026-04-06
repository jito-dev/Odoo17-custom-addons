from odoo import models, fields, api
from odoo.exceptions import UserError


class MgmtProcessWizard(models.TransientModel):
    _name = 'mgmt.process.wizard'
    _description = 'Management Accounting Process Wizard'

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
    action_type = fields.Selection(
        selection=[
            ('mapping', 'Apply Classification Rules'),
            ('allocation', 'Apply Allocation Rules'),
        ],
        string='Action',
        required=True,
        default='mapping',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self._context.get('active_model') == 'mgmt.period':
            res['period_id'] = self._context.get('active_id')
        if self._context.get('default_action_type'):
            res['action_type'] = self._context['default_action_type']
        return res

    def action_process(self):
        self.ensure_one()
        self.period_id._check_period_open()

        if self.action_type == 'mapping':
            return self._process_mapping()
        elif self.action_type == 'allocation':
            return self._process_allocation()

    def _process_mapping(self):
        """Apply classification rules to unprocessed source lines."""
        period = self.period_id
        LedgerLine = self.env['mgmt.ledger.line']

        # Clear existing mapping lines for this period
        existing_mapping_lines = LedgerLine.search([
            ('period_id', '=', period.id),
            ('origin_type', '=', 'mapping'),
        ])
        if existing_mapping_lines:
            existing_mapping_lines.unlink()

        # Reset source line states
        source_lines = self.env['mgmt.source.line'].search([
            ('period_id', '=', period.id),
        ])
        source_lines.write({'state': 'draft'})

        # Get active mapping rules ordered by sequence
        rules = self.env['mgmt.mapping.rule'].search([
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
        ], order='sequence, id')

        # Get default account mappings as fallback
        default_mappings = {}
        for mapping in self.env['mgmt.account.mapping'].search([
            ('company_id', '=', self.company_id.id),
        ]):
            default_mappings[mapping.financial_account_id.id] = mapping.mgmt_account_id.id

        mapped_count = 0
        unmapped_count = 0
        vals_list = []

        for source_line in source_lines:
            target_account = False
            applied_rule = False

            # Try rules in sequence order
            for rule in rules:
                if rule._match(source_line):
                    target_account = rule.target_mgmt_account_id
                    applied_rule = rule
                    break

            # Fallback to default mapping
            if not target_account and source_line.financial_account_id.id in default_mappings:
                target_account = self.env['mgmt.account'].browse(
                    default_mappings[source_line.financial_account_id.id]
                )

            if target_account:
                vals_list.append({
                    'period_id': period.id,
                    'mgmt_account_id': target_account.id,
                    'date': source_line.date,
                    'label': source_line.label,
                    'debit': source_line.debit,
                    'credit': source_line.credit,
                    'currency_id': source_line.currency_id.id,
                    'company_id': self.company_id.id,
                    'partner_id': source_line.partner_id.id if source_line.partner_id else False,
                    'analytic_distribution': source_line.analytic_distribution,
                    'origin_type': 'mapping',
                    'source_line_id': source_line.id,
                    'source_move_line_id': source_line.source_move_line_id.id,
                    'mapping_rule_id': applied_rule.id if applied_rule else False,
                })
                source_line.state = 'processed'
                mapped_count += 1
            else:
                unmapped_count += 1

        if vals_list:
            LedgerLine.create(vals_list)

        msg_type = 'success' if unmapped_count == 0 else 'warning'
        message = f'{mapped_count} lines classified.'
        if unmapped_count:
            message += f' {unmapped_count} lines remain unclassified.'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Classification Complete',
                'message': message,
                'type': msg_type,
                'sticky': unmapped_count > 0,
            },
        }

    def _process_allocation(self):
        """Apply allocation rules to the period's ledger lines."""
        period = self.period_id
        LedgerLine = self.env['mgmt.ledger.line']

        # Clear existing allocation lines for this period
        existing_alloc_lines = LedgerLine.search([
            ('period_id', '=', period.id),
            ('origin_type', '=', 'allocation'),
        ])
        if existing_alloc_lines:
            existing_alloc_lines.unlink()

        rules = self.env['mgmt.allocation.rule'].search([
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
        ], order='sequence, id')

        allocation_count = 0
        vals_list = []

        for rule in rules:
            # Sum ledger lines for the source account (excluding allocation lines)
            source_lines = LedgerLine.search([
                ('period_id', '=', period.id),
                ('mgmt_account_id', '=', rule.source_mgmt_account_id.id),
                ('origin_type', '!=', 'allocation'),
            ])
            source_balance = sum(source_lines.mapped('balance'))

            if not source_balance:
                continue

            # Create offsetting entry on source account
            vals_list.append({
                'period_id': period.id,
                'mgmt_account_id': rule.source_mgmt_account_id.id,
                'date': period.date_start,
                'label': f'Allocation: {rule.name} (offset)',
                'debit': abs(source_balance) if source_balance < 0 else 0,
                'credit': source_balance if source_balance > 0 else 0,
                'currency_id': self.company_id.currency_id.id,
                'company_id': self.company_id.id,
                'origin_type': 'allocation',
                'allocation_rule_id': rule.id,
            })

            # Distribute to targets
            if rule.method == 'percentage':
                for line in rule.line_ids:
                    amount = self.company_id.currency_id.round(
                        source_balance * line.percentage / 100.0
                    )
                    vals_list.append({
                        'period_id': period.id,
                        'mgmt_account_id': line.target_mgmt_account_id.id,
                        'date': period.date_start,
                        'label': f'Allocation: {rule.name} ({line.percentage}%)',
                        'debit': amount if amount > 0 else 0,
                        'credit': abs(amount) if amount < 0 else 0,
                        'currency_id': self.company_id.currency_id.id,
                        'company_id': self.company_id.id,
                        'origin_type': 'allocation',
                        'allocation_rule_id': rule.id,
                    })
            elif rule.method == 'fixed_amount':
                for line in rule.line_ids:
                    amount = line.fixed_amount
                    vals_list.append({
                        'period_id': period.id,
                        'mgmt_account_id': line.target_mgmt_account_id.id,
                        'date': period.date_start,
                        'label': f'Allocation: {rule.name} (fixed)',
                        'debit': amount if amount > 0 else 0,
                        'credit': abs(amount) if amount < 0 else 0,
                        'currency_id': self.company_id.currency_id.id,
                        'company_id': self.company_id.id,
                        'origin_type': 'allocation',
                        'allocation_rule_id': rule.id,
                    })

            allocation_count += 1

        if vals_list:
            LedgerLine.create(vals_list)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Allocation Complete',
                'message': f'{allocation_count} allocation rules applied.',
                'type': 'success',
                'sticky': False,
            },
        }
