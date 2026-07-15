# -*- coding: utf-8 -*-
"""Credit-note pipeline for Upwork refunds.

A refund document looks like a 3-page service doc:
  • page 2 = refund WE issue to the client     → Customer Credit Note (out_refund)
  • page 3 = "Service Fee return" from Upwork   → Vendor Credit Note (in_refund)

Built directly from transaction data (amounts/partner are known); the split page
is attached as proof. Reconciled against the Upwork Wallet line:
  • customer credit note ↔ the refund *outflow*
  • vendor credit note   ↔ the fee-return *inflow*
"""

import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class UsaTransactionRefundCreation(models.Model):
    _inherit = 'usa.transaction'

    customer_refund_id = fields.Many2one(
        'account.move', string='Customer Credit Note',
        readonly=True, copy=False, ondelete='set null',
        domain="[('move_type', '=', 'out_refund')]",
    )
    vendor_refund_id = fields.Many2one(
        'account.move', string='Vendor Credit Note',
        readonly=True, copy=False, ondelete='set null',
        domain="[('move_type', '=', 'in_refund')]",
    )
    has_customer_refund = fields.Boolean(compute='_compute_has_refunds')
    has_vendor_refund = fields.Boolean(compute='_compute_has_refunds')
    is_refund_reconciled = fields.Boolean(compute='_compute_refund_reconciled')

    @api.depends('customer_refund_id', 'vendor_refund_id')
    def _compute_has_refunds(self):
        for rec in self:
            rec.has_customer_refund = bool(rec.customer_refund_id)
            rec.has_vendor_refund = bool(rec.vendor_refund_id)

    @api.depends('statement_line_id.is_reconciled')
    def _compute_refund_reconciled(self):
        for rec in self:
            rec.is_refund_reconciled = (
                rec.statement_line_id.is_reconciled
                if rec.statement_line_id else False)

    # ── Actions ────────────────────────────────────────────────────────────────

    def action_create_customer_refund(self):
        return self._process_refund_batch('customer')

    def action_create_vendor_refund(self):
        return self._process_refund_batch('vendor')

    def action_open_customer_refund(self):
        self.ensure_one()
        if not self.customer_refund_id:
            raise UserError(_("No customer credit note linked to this transaction."))
        return self._open_move(self.customer_refund_id)

    def action_open_vendor_refund(self):
        self.ensure_one()
        if not self.vendor_refund_id:
            raise UserError(_("No vendor credit note linked to this transaction."))
        return self._open_move(self.vendor_refund_id)

    def _open_move(self, move):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ── Batch ──────────────────────────────────────────────────────────────────

    def _process_refund_batch(self, side):
        created = skipped = posted = reconciled = 0
        errors = []
        want_mode = 'customer_refund' if side == 'customer' else 'vendor_refund'
        for rec in self:
            existing = rec.customer_refund_id if side == 'customer' else rec.vendor_refund_id
            if existing or rec.injection_mode != want_mode or not rec.upwork_invoice_pdf:
                skipped += 1
                continue
            try:
                move = rec._create_refund_move(side)
                if not move:
                    skipped += 1
                    continue
                created += 1
                if rec._check_refund(move):
                    move.action_post()
                    posted += 1
                    if rec.statement_line_id and rec._auto_reconcile_refund(move, side):
                        reconciled += 1
            except Exception as e:
                errors.append(f'{rec.record_id}: {str(e)[:100]}')
                _logger.exception(
                    "Error creating %s refund for Upwork TX %s", side, rec.record_id)
        total = len(self)
        msg = [f'{created}/{total} credit notes created.']
        if posted:
            msg.append(f'{posted} posted.')
        if reconciled:
            msg.append(f'{reconciled} reconciled.')
        if skipped:
            msg.append(f'{skipped} skipped.')
        if errors:
            msg.append(f'{len(errors)} errors: ' + '; '.join(errors[:3]))
        return self._usa_notify(
            _('Create Credit Notes'), ' '.join(msg),
            'success' if created and not errors else ('warning' if errors else 'info'),
            bool(errors))

    # ── Creation ───────────────────────────────────────────────────────────────

    def _create_refund_move(self, side):
        """Create an out_refund (customer) or in_refund (vendor) from tx data,
        attaching the split refund page as the main attachment."""
        self.ensure_one()
        if not self.upwork_invoice_pdf:
            return False

        settings = self.env['usa.settings'].sudo()._get_singleton()
        account = settings._get_account_for_transaction(self)
        amount = abs(self.transaction_amount_raw or self.amount_credited_raw or 0.0)

        if side == 'customer':
            move_type = 'out_refund'
            journal = self.env['account.journal'].search([
                ('type', '=', 'sale'), ('company_id', '=', self.env.company.id)], limit=1)
            partner = self._find_or_create_customer_partner()
            jname = 'sales'
        else:
            move_type = 'in_refund'
            journal = self.env['account.journal'].search([
                ('type', '=', 'purchase'), ('company_id', '=', self.env.company.id)], limit=1)
            partner = self._get_upwork_vendor()
            jname = 'purchase'
        if not journal:
            raise UserError(_("No %s journal found. Please create one first.") % jname)

        line_vals = {
            'name': self.description_ui or self.description or _('Upwork refund'),
            'quantity': 1,
            'price_unit': amount,
        }
        if account:
            line_vals['account_id'] = account.id

        invoice_date = self._get_accounting_date()  # Upwork review-due (ledger) date
        tx_ref = 'T%s' % self.record_id   # e.g. T925967919
        move = self.env['account.move'].create({
            'move_type': move_type,
            'journal_id': journal.id,
            'partner_id': partner.id if partner else False,
            'invoice_date': invoice_date,
            'date': invoice_date,  # Accounting Date = Upwork ledger date (forced)
            'invoice_origin': self.record_id,
            'ref': tx_ref,
            'payment_reference': tx_ref,
            'invoice_line_ids': [(0, 0, line_vals)],
        })

        filename = self.upwork_invoice_filename or 'upwork_refund.pdf'
        pdf_data = self.with_context(bin_size=False).upwork_invoice_pdf
        att = self.env['ir.attachment'].create({
            'name': filename,
            'datas': pdf_data,
            'mimetype': 'application/pdf',
            'res_model': 'account.move',
            'res_id': move.id,
        })
        move.with_context(no_new_invoice=True).message_post(
            attachment_ids=[att.id],
            body=_("Refund document attached from Upwork transaction %s", self.record_id))
        att.with_context(skip_ai_extract=True).register_as_main_attachment(force=True)

        if side == 'customer':
            self.customer_refund_id = move.id
        else:
            self.vendor_refund_id = move.id
        return move

    def _get_upwork_vendor(self):
        """Find/create the Upwork vendor partner for vendor credit notes."""
        Partner = self.env['res.partner']
        vendor = Partner.search(
            [('name', 'ilike', 'Upwork'), ('supplier_rank', '>', 0)], limit=1) \
            or Partner.search([('name', 'ilike', 'Upwork')], limit=1)
        if not vendor:
            vendor = Partner.create({
                'name': 'Upwork Global Inc.',
                'is_company': True,
                'supplier_rank': 1,
                'company_id': self.env.company.id,
            })
        return vendor

    # ── Confidence + reconciliation ───────────────────────────────────────────

    def _check_refund(self, move):
        self.ensure_one()
        if not move.partner_id or not move.invoice_line_ids or not move.invoice_date:
            return False
        tx_amount = abs(self.transaction_amount_raw or 0)
        m_amount = move.amount_total
        if tx_amount and m_amount:
            if abs(m_amount - tx_amount) / tx_amount > 0.05:
                return False
        elif tx_amount and not m_amount:
            return False
        return True

    def _auto_reconcile_refund(self, move, side):
        """Reconcile the posted credit note against the wallet statement line."""
        self.ensure_one()
        stmt = self.statement_line_id
        if not move or not stmt or move.state != 'posted':
            return False
        acct_type = 'asset_receivable' if side == 'customer' else 'liability_payable'
        open_line = move.line_ids.filtered(
            lambda l: l.account_id.account_type == acct_type and not l.reconciled)
        if not open_line:
            return False
        try:
            widget = self.env['bank.rec.widget'].new({'st_line_id': stmt.id})
            widget._ensure_loaded_lines()
            widget._action_add_new_amls(open_line[:1])
            widget._action_validate()
            return True
        except Exception as e:
            _logger.warning(
                "Auto-reconcile refund failed for move %s / statement line %s: %s",
                move.id, stmt.id, e)
            return False
