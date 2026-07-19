# -*- coding: utf-8 -*-

import logging
import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RevolutTransactionCustomerInvoice(models.Model):
    _inherit = 'revolut.transaction'

    customer_invoice_id = fields.Many2one(
        'account.move', string='Customer Invoice',
        readonly=True, copy=False, ondelete='set null',
        domain="[('move_type', '=', 'out_invoice')]",
    )
    has_customer_invoice = fields.Boolean(
        string='Has Customer Invoice',
        compute='_compute_has_customer_invoice',
    )
    # Inline manual picker — stage an unpaid customer invoice, then attach it with
    # the button (staging only; cleared right after attach). Domain mirrors the
    # 'Match & Attach' wizard's notion of an owed invoice (see _find_matching_invoice).
    manual_invoice_pick_id = fields.Many2one(
        'account.move', string='Attach Existing Invoice',
        copy=False, ondelete='set null',
        domain="[('move_type', '=', 'out_invoice'),"
               " ('company_id', '=', company_id),"
               " ('state', 'in', ('draft', 'posted')),"
               " ('payment_state', 'in', ('not_paid', 'partial'))]",
        help="Pick an unpaid customer invoice by its number (e.g. INV/2026/00042) "
             "and click 'Attach Invoice'. Only unpaid/partially-paid invoices of "
             "this company are listed.",
    )
    customer_invoice_preview_html = fields.Html(
        string='Customer Invoice Preview', sanitize=False,
        compute='_compute_customer_invoice_preview',
    )

    @api.depends('customer_invoice_id')
    def _compute_has_customer_invoice(self):
        for rec in self:
            rec.has_customer_invoice = bool(rec.customer_invoice_id)

    @api.depends('customer_invoice_id', 'customer_invoice_id.message_main_attachment_id')
    def _compute_customer_invoice_preview(self):
        for rec in self:
            html = ''
            inv = rec.customer_invoice_id
            att = inv.message_main_attachment_id if inv else False
            if inv and not att:
                html = '<span class="text-muted">Invoice linked — no document attached to it.</span>'
            elif att:
                mt = (att.mimetype or '').lower()
                if mt.startswith('image/'):
                    html = (
                        '<img src="/web/image/ir.attachment/%s/datas" '
                        'style="max-width:100%%;max-height:340px;object-fit:contain;'
                        'border:1px solid #dee2e6;border-radius:4px;"/>' % att.id)
                elif mt == 'application/pdf':
                    html = (
                        '<iframe src="/web/content/%s?download=false#toolbar=0" '
                        'style="width:100%%;height:360px;border:1px solid #dee2e6;'
                        'border-radius:4px;"></iframe>' % att.id)
                else:
                    html = (
                        '<a href="/web/content/%s?download=false" target="_blank" '
                        'class="btn btn-secondary btn-sm"><i class="fa fa-file-o me-1"></i>'
                        'Open document</a>' % att.id)
            rec.customer_invoice_preview_html = html

    def action_open_invoice_link_wizard(self):
        """Open the 'Match & Attach Customer Invoices' wizard for the selected
        (incoming) transactions: find existing Odoo customer invoices by
        number/reference, else partner-name/amount/date, review, then link them."""
        if not self:
            raise UserError(_("Select at least one transaction first."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Match & Attach Customer Invoices'),
            'res_model': 'revolut.invoice.link.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_transaction_ids': [(6, 0, self.ids)]},
        }

    def action_unlink_customer_invoice(self):
        """Unlink the customer invoice from the selected transactions: clear
        customer_invoice_id, drop the invoice document from receipts, and
        unreconcile the statement line if it was reconciled with the invoice."""
        cleared = unreconciled = skipped = 0
        for rec in self:
            inv = rec.customer_invoice_id
            if not inv:
                skipped += 1
                continue
            if rec.statement_line_id and rec.statement_line_id.is_reconciled:
                try:
                    for ml in rec.statement_line_id.move_id.line_ids:
                        (ml.matched_debit_ids + ml.matched_credit_ids).unlink()
                    unreconciled += 1
                except Exception as e:  # noqa: BLE001
                    _logger.warning("Unlink invoice: could not unreconcile tx %s: %s", rec.id, e)
            main_att = inv.message_main_attachment_id
            if main_att and main_att in rec.invoice_attachment_ids:
                rec.invoice_attachment_ids = [(3, main_att.id)]
            rec.customer_invoice_id = False
            cleared += 1
        msg = _('%s invoice(s) unlinked, %s unreconciled, %s skipped.') % (
            cleared, unreconciled, skipped)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Unlink Customer Invoice'),
                'message': msg,
                'type': 'warning' if not cleared else 'success',
                'sticky': False,
            },
        }

    def action_attach_manual_invoice(self):
        """Attach the manually-picked customer invoice to this transaction.

        The per-record counterpart of the batch 'Match & Attach Customer Invoices'
        wizard: link the chosen invoice as ``customer_invoice_id`` (a reference,
        not a copy) and surface its main document as a receipt — same effect as
        ``revolut.invoice.link.wizard.action_attach``. Reconciliation stays a
        separate step ('Reconcile invoice & tx'). Blocks re-using an invoice
        already linked to another transaction to avoid double reconciliation."""
        self.ensure_one()
        inv = self.manual_invoice_pick_id
        if not inv:
            raise UserError(_("Pick a customer invoice to attach first."))
        if inv.move_type != 'out_invoice':
            raise UserError(_("Only customer invoices can be attached here."))
        other = self.search(
            [('customer_invoice_id', '=', inv.id), ('id', '!=', self.id)], limit=1)
        if other:
            raise UserError(_(
                "Invoice %(inv)s is already attached to transaction %(tx)s. "
                "Unlink it there first.",
                inv=inv.display_name,
                tx=other.display_name or other.revolut_id,
            ))
        self.customer_invoice_id = inv.id
        # Link the invoice's main document as a receipt (counter + preview),
        # matching the wizard — keep the file, just reference it.
        main_att = inv.message_main_attachment_id
        if main_att and main_att not in self.invoice_attachment_ids:
            self.invoice_attachment_ids = [(4, main_att.id)]
        self.manual_invoice_pick_id = False
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Customer Invoice Attached'),
                'message': _(
                    'Linked %s. Reconcile via "Reconcile invoice & tx".',
                    inv.display_name),
                'type': 'success',
                'sticky': False,
                # Reload the form so the section flips to the linked/preview state.
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_reconcile_customer_invoice(self):
        """Post the customer invoice (if draft) and reconcile its receivable with
        the incoming bank statement line. Mirror of 'Reconcile injected bill & tx'
        for the receivable side."""
        posted = reconciled = skipped = 0
        errors = []
        for rec in self:
            inv = rec.customer_invoice_id
            stmt_line = rec.statement_line_id
            if not inv or not stmt_line:
                skipped += 1
                continue
            if stmt_line.is_reconciled:
                skipped += 1
                continue
            label = rec.merchant_name or rec.description or rec.revolut_id
            try:
                if inv.state == 'draft':
                    inv.action_post()
                    posted += 1
                if inv.state != 'posted':
                    errors.append(f'{label}: invoice is not posted')
                else:
                    ok, reason = rec._auto_reconcile_invoice()
                    if ok:
                        reconciled += 1
                    else:
                        errors.append(f'{label}: {reason or "could not reconcile"}')
            except Exception as e:  # noqa: BLE001
                errors.append(f'{label}: {str(e).strip().splitlines()[0][:200] if str(e).strip() else type(e).__name__}')
                _logger.exception(
                    "Error reconciling invoice for revolut TX %s", rec.revolut_id)

        total = len(self)
        msg_parts = []
        if posted:
            msg_parts.append(f'{posted} invoices posted.')
        if reconciled:
            msg_parts.append(f'{reconciled}/{total} reconciled.')
        if skipped:
            msg_parts.append(f'{skipped} skipped.')
        if errors:
            msg_parts.append(f'{len(errors)} errors: ' + '; '.join(errors[:3]))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reconcile invoice & tx'),
                'message': ' '.join(msg_parts) or _('Nothing to reconcile.'),
                'type': 'success' if reconciled and not errors else ('warning' if errors else 'info'),
                'sticky': bool(errors),
            },
        }

    def action_unreconcile_invoice(self):
        """Reverse of 'Reconcile invoice & tx': remove the reconciliation between
        the bank statement line and the invoice, keeping the link and the invoice."""
        done = skipped = 0
        for rec in self:
            stmt_line = rec.statement_line_id
            if not rec.customer_invoice_id or not stmt_line or not stmt_line.is_reconciled:
                skipped += 1
                continue
            try:
                for ml in stmt_line.move_id.line_ids:
                    (ml.matched_debit_ids + ml.matched_credit_ids).unlink()
                done += 1
            except Exception as e:  # noqa: BLE001
                _logger.warning("Unreconcile invoice failed for tx %s: %s", rec.id, e)
                skipped += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Unreconcile invoice & tx'),
                'message': _('%s unreconciled, %s skipped.') % (done, skipped),
                'type': 'success' if done else 'warning',
                'sticky': False,
            },
        }

    def _auto_reconcile_invoice(self):
        """Reconcile the posted customer invoice's receivable with the bank
        statement line via Odoo's bank.rec.widget. Returns (ok, reason). Mirrors
        `_auto_reconcile_bill` but on the receivable side; reuses the shared
        currency-alignment / self-heal / savepoint hardening."""
        self.ensure_one()
        inv = self.customer_invoice_id
        stmt_line = self.statement_line_id
        if not inv or not stmt_line:
            return False, _('missing invoice or bank line')
        if inv.state != 'posted':
            return False, _('invoice is not posted')

        receivable = inv.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable')
        if not receivable:
            return False, _('the invoice has no receivable line')

        # Self-heal a stale/partial reconciliation from an earlier failed attempt.
        stale = receivable.filtered(
            lambda l: l.reconciled or l.matched_debit_ids or l.matched_credit_ids)
        if stale:
            stale.remove_move_reconcile()

        inv_receivable = receivable.filtered(lambda l: not l.reconciled)
        if not inv_receivable:
            return False, _('no unreconciled receivable line on the invoice')

        # Carry the invoice's currency on the bank line so a foreign invoice
        # reconciles 1:1 and the rate gap posts to FX gain/loss.
        self._align_bank_line_to_bill_currency(inv, stmt_line)

        try:
            with self.env.cr.savepoint():
                widget = self.env['bank.rec.widget'].new({'st_line_id': stmt_line.id})
                widget._ensure_loaded_lines()
                widget._action_add_new_amls(inv_receivable[:1])
                widget._action_validate()
            return True, ''
        except Exception as e:  # noqa: BLE001
            _logger.exception(
                "Auto-reconcile failed for invoice %s / statement line %s",
                inv.id, stmt_line.id)
            reason = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
            return False, reason

    def _find_matching_invoice(self):
        """Find the best existing customer invoice (account.move, out_invoice) for
        this transaction. Returns (invoice, confidence, reason); empty recordset if
        none. Invoice number/reference + amount is decisive; else partner-name +
        amount + date."""
        self.ensure_one()
        Move = self.env['account.move']
        amount = abs(self.amount or 0.0) or abs(self.bill_amount or 0.0)
        if amount <= 0:
            return Move, 'none', _('No amount to match against.')
        tol = max(0.02, amount * 0.01)  # 1% or 2 cents — absorbs FX/rounding

        linked = self.search([('customer_invoice_id', '!=', False)]).mapped('customer_invoice_id').ids
        domain = [
            ('move_type', '=', 'out_invoice'),
            ('company_id', '=', self.company_id.id),
            ('state', 'in', ('posted', 'draft')),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('amount_total', '>=', amount - tol),
            ('amount_total', '<=', amount + tol),
        ]
        if linked:
            domain.append(('id', 'not in', linked))
        candidates = Move.search(domain)
        if not candidates:
            return Move, 'none', _('No unmatched customer invoice near %.2f.', amount)

        # 1) Invoice number / reference appears in the tx reference or description.
        hay_ref = ' '.join(filter(None, [self.reference, self.description])).lower()
        for inv in candidates:
            for token in (inv.name, inv.ref, inv.payment_reference):
                t = (token or '').strip().lower()
                if t and len(t) >= 4 and t in hay_ref:
                    return inv, 'high', _('Reference "%s" matches; amount %.2f.', token, amount)

        # 2) Customer name + date fallback.
        hay_name = ' '.join(filter(None, [self.description, self.merchant_name])).lower()
        td = self.settlement_date_local or self.settlement_date
        best_low = Move
        for inv in candidates:
            tokens = [t for t in re.split(r'\W+', (inv.partner_id.name or '').lower()) if len(t) > 2]
            overlap = [t for t in tokens if t in hay_name]
            days = abs((inv.invoice_date - td).days) if (inv.invoice_date and td) else None
            if overlap and days is not None and days <= 14:
                return inv, 'medium', _('Name "%s" + amount %.2f + date ±%sd.',
                                        inv.partner_id.name, amount, days)
            if overlap and not best_low:
                best_low = inv
        if best_low:
            return best_low, 'low', _('Name "%s" + amount %.2f (date not close).',
                                      best_low.partner_id.name, amount)
        if len(candidates) == 1:
            return candidates, 'low', _('Only one unmatched invoice near %.2f.', amount)
        return Move, 'none', _('%s invoices near %.2f; no reference/name match.', len(candidates), amount)
