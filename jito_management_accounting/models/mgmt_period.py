from odoo import models, fields, api
from odoo.exceptions import UserError


class MgmtPeriod(models.Model):
    _name = 'mgmt.period'
    _description = 'Management Accounting Period'
    _inherit = ['mail.thread']
    _order = 'date_start desc, id desc'

    name = fields.Char(
        string='Name',
        required=True,
    )
    date_start = fields.Date(
        string='Start Date',
        required=True,
    )
    date_end = fields.Date(
        string='End Date',
        required=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('open', 'Open'),
            ('closed', 'Closed'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    lock_date = fields.Date(
        string='Lock Date',
        help='Management lock date for this period. Independent of financial lock dates.',
    )
    ledger_line_ids = fields.One2many(
        'mgmt.ledger.line',
        'period_id',
        string='Ledger Lines',
    )
    source_line_ids = fields.One2many(
        'mgmt.source.line',
        'period_id',
        string='Source Lines',
    )
    notes = fields.Text(
        string='Notes',
    )
    source_line_count = fields.Integer(
        string='Source Lines',
        compute='_compute_counts',
    )
    ledger_line_count = fields.Integer(
        string='Ledger Lines',
        compute='_compute_counts',
    )

    _sql_constraints = [
        ('date_company_uniq', 'UNIQUE(date_start, date_end, company_id)',
         'Period date range must be unique per company.'),
    ]

    @api.depends('source_line_ids', 'ledger_line_ids')
    def _compute_counts(self):
        for period in self:
            period.source_line_count = len(period.source_line_ids)
            period.ledger_line_count = len(period.ledger_line_ids)

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for period in self:
            if period.date_end < period.date_start:
                raise UserError('End date must be on or after start date.')

    def action_open(self):
        for period in self:
            if period.state != 'draft':
                raise UserError('Only draft periods can be opened.')
            period.state = 'open'

    def action_close(self):
        for period in self:
            if period.state != 'open':
                raise UserError('Only open periods can be closed.')
            period.write({
                'state': 'closed',
                'lock_date': period.date_end,
            })

    def action_reopen(self):
        for period in self:
            if period.state != 'closed':
                raise UserError('Only closed periods can be reopened.')
            later_closed = self.search([
                ('company_id', '=', period.company_id.id),
                ('date_start', '>', period.date_end),
                ('state', '=', 'closed'),
            ], limit=1)
            if later_closed:
                raise UserError(
                    f'Cannot reopen this period because a later period '
                    f'"{later_closed.name}" is still closed.'
                )
            period.write({
                'state': 'open',
                'lock_date': False,
            })

    def action_view_source_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Source Lines - {self.name}',
            'res_model': 'mgmt.source.line',
            'view_mode': 'tree,form',
            'domain': [('period_id', '=', self.id)],
            'context': {'default_period_id': self.id},
        }

    def action_view_ledger_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Ledger Lines - {self.name}',
            'res_model': 'mgmt.ledger.line',
            'view_mode': 'tree,pivot,graph,form',
            'domain': [('period_id', '=', self.id)],
            'context': {'default_period_id': self.id},
        }

    def action_reset_mapping(self):
        """Delete all classification ledger lines and reset source lines to draft."""
        for period in self:
            period._check_period_open()
            mapping_lines = self.env['mgmt.ledger.line'].search([
                ('period_id', '=', period.id),
                ('origin_type', '=', 'mapping'),
            ])
            # Collect source lines before deleting ledger lines
            source_lines = mapping_lines.mapped('source_line_id')
            count = len(mapping_lines)
            if mapping_lines:
                mapping_lines.unlink()
            if source_lines:
                source_lines.write({'state': 'draft'})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Classification Reset',
                'message': f'{count} classification ledger lines removed, {len(source_lines)} source lines reset to draft.',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_reset_allocations(self):
        """Delete all allocation ledger lines for this period."""
        for period in self:
            period._check_period_open()
            alloc_lines = self.env['mgmt.ledger.line'].search([
                ('period_id', '=', period.id),
                ('origin_type', '=', 'allocation'),
            ])
            count = len(alloc_lines)
            if alloc_lines:
                alloc_lines.unlink()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Allocations Reset',
                'message': f'{count} allocation ledger lines removed.',
                'type': 'success',
                'sticky': False,
            },
        }

    def _check_period_open(self):
        """Raise UserError if any period in self is not open."""
        for period in self:
            if period.state == 'closed':
                raise UserError(
                    f'Period "{period.name}" is closed. '
                    f'No modifications are allowed.'
                )
            if period.state == 'draft':
                raise UserError(
                    f'Period "{period.name}" is in draft. '
                    f'Open it before making changes.'
                )
