# -*- coding: utf-8 -*-
"""Customer-invoice pipeline for Upwork revenue transactions.

Mirrors usa_bill_creation.py (vendor bills) but builds an out_invoice straight
from the transaction data (the figures are ours — Upwork issued the invoice on
our behalf; the split page-2 PDF is attached as proof) and reconciles the
Upwork Wallet *inflow* statement line against the invoice receivable.
"""

import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class UsaTransactionCustomerInvoiceCreation(models.Model):
    _inherit = 'usa.transaction'

    customer_invoice_id = fields.Many2one(
        'account.move', string='Customer Invoice',
        readonly=True, copy=False, ondelete='set null',
        domain="[('move_type', '=', 'out_invoice')]",
    )
    has_customer_invoice = fields.Boolean(
        string='Has Customer Invoice',
        compute='_compute_has_customer_invoice',
    )
    is_customer_invoice_reconciled = fields.Boolean(
        string='Customer Invoice Reconciled',
        compute='_compute_customer_invoice_reconciled',
    )

    @api.depends('customer_invoice_id')
    def _compute_has_customer_invoice(self):
        for rec in self:
            rec.has_customer_invoice = bool(rec.customer_invoice_id)

    @api.depends('statement_line_id.is_reconciled')
    def _compute_customer_invoice_reconciled(self):
        for rec in self:
            rec.is_customer_invoice_reconciled = (
                rec.statement_line_id.is_reconciled
                if rec.statement_line_id else False
            )

    # ── Actions ────────────────────────────────────────────────────────────────

    def action_create_customer_invoice(self):
        """Create customer invoice, post if confident, auto-reconcile."""
        return self._process_customer_invoice_batch(
            auto_post=True, auto_reconcile=True,
            title=_('Create Customer Invoices & Reconcile'))

    def action_create_draft_customer_invoice(self):
        """Create draft customer invoice (no post / no reconcile)."""
        return self._process_customer_invoice_batch(
            auto_post=False, auto_reconcile=False,
            title=_('Create Draft Customer Invoices'))

    def action_reconcile_customer_invoice(self):
        """Post (if draft) and reconcile the customer invoice with the statement line."""
        posted = reconciled = skipped = 0
        errors = []
        for rec in self:
            inv = rec.customer_invoice_id
            stmt = rec.statement_line_id
            if not inv or not stmt or stmt.is_reconciled:
                skipped += 1
                continue
            try:
                if inv.state == 'draft':
                    inv.action_post()
                    posted += 1
                if inv.state == 'posted' and rec._auto_reconcile_customer_invoice():
                    reconciled += 1
                else:
                    errors.append(rec.description or rec.record_id)
            except Exception as e:
                errors.append(f'{rec.record_id}: {str(e)[:100]}')
                _logger.exception(
                    "Error reconciling customer invoice for Upwork TX %s", rec.record_id)
        msg = []
        if posted:
            msg.append(f'{posted} posted.')
        if reconciled:
            msg.append(f'{reconciled} reconciled.')
        if skipped:
            msg.append(f'{skipped} skipped.')
        if errors:
            msg.append(f'{len(errors)} errors: ' + '; '.join(errors[:3]))
        return self._usa_notify(
            _('Reconcile Customer Invoices'),
            ' '.join(msg) or _('Nothing to reconcile.'),
            'success' if reconciled and not errors else ('warning' if errors else 'info'),
            bool(errors))

    def action_open_customer_invoice(self):
        self.ensure_one()
        if not self.customer_invoice_id:
            raise UserError(_("No customer invoice linked to this transaction."))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.customer_invoice_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ── Batch ──────────────────────────────────────────────────────────────────

    def _process_customer_invoice_batch(self, auto_post=True, auto_reconcile=True, title=''):
        created = skipped = posted = reconciled = 0
        errors = []
        for rec in self:
            if rec.customer_invoice_id:
                skipped += 1
                continue
            if rec.injection_mode != 'customer_invoice':
                skipped += 1
                continue
            if not rec.upwork_invoice_pdf:
                skipped += 1
                continue
            try:
                inv = rec._create_customer_invoice_from_service_pdf()
                if not inv:
                    skipped += 1
                    continue
                created += 1
                if auto_post and rec._check_customer_invoice(inv):
                    inv.action_post()
                    posted += 1
                    if auto_reconcile and rec.statement_line_id \
                            and rec._auto_reconcile_customer_invoice():
                        reconciled += 1
            except Exception as e:
                errors.append(f'{rec.record_id}: {str(e)[:100]}')
                _logger.exception(
                    "Error creating customer invoice for Upwork TX %s", rec.record_id)
        total = len(self)
        msg = [f'{created}/{total} customer invoices created.']
        if posted:
            msg.append(f'{posted} posted.')
        if reconciled:
            msg.append(f'{reconciled} reconciled.')
        if skipped:
            msg.append(f'{skipped} skipped.')
        if errors:
            msg.append(f'{len(errors)} errors: ' + '; '.join(errors[:3]))
        return self._usa_notify(
            title or _('Create Customer Invoices'), ' '.join(msg),
            'success' if created and not errors else ('warning' if errors else 'info'),
            bool(errors))

    # ── Creation ───────────────────────────────────────────────────────────────

    def _create_customer_invoice_from_service_pdf(self):
        """Create a posted-ready out_invoice from this transaction's own data,
        attaching the split service-invoice page as the main attachment."""
        self.ensure_one()
        if not self.upwork_invoice_pdf:
            return False

        journal = self.env['account.journal'].search([
            ('type', '=', 'sale'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not journal:
            raise UserError(_("No sales journal found. Please create one first."))

        partner = self._find_or_create_customer_partner()
        settings = self.env['usa.settings'].sudo()._get_singleton()
        revenue_account = settings._get_account_for_transaction(self)

        # Auto-enrich the client's billing address (once per address-less client)
        if settings.auto_enrich_clients and self._partner_needs_address(partner) \
                and partner.upwork_address_enrich_state == 'none':
            self._enqueue_client_enrichment(partner)

        amount = abs(self.transaction_amount_raw or self.amount_credited_raw or 0.0)

        line_vals = {
            'name': self.description_ui or self.description or _('Upwork services'),
            'quantity': 1,
            'price_unit': amount,
        }
        if revenue_account:
            line_vals['account_id'] = revenue_account.id

        invoice_date = self._get_accounting_date()  # Upwork review-due (ledger) date
        tx_ref = 'T%s' % self.record_id   # e.g. T925967919 — matches the vendor bill ref
        inv = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'journal_id': journal.id,
            'partner_id': partner.id if partner else False,
            'invoice_date': invoice_date,
            'date': invoice_date,  # Accounting Date = Upwork ledger date (forced)
            'invoice_origin': self.record_id,
            'ref': tx_ref,
            'payment_reference': tx_ref,
            'invoice_line_ids': [(0, 0, line_vals)],
        })

        # Attach the service-invoice page as proof / main attachment
        filename = self.upwork_invoice_filename or 'upwork_service_invoice.pdf'
        pdf_data = self.with_context(bin_size=False).upwork_invoice_pdf
        att = self.env['ir.attachment'].create({
            'name': filename,
            'datas': pdf_data,
            'mimetype': 'application/pdf',
            'res_model': 'account.move',
            'res_id': inv.id,
        })
        inv.with_context(no_new_invoice=True).message_post(
            attachment_ids=[att.id],
            body=_("Service invoice attached from Upwork transaction %s", self.record_id))
        att.register_as_main_attachment(force=True)

        self.customer_invoice_id = inv.id
        return inv

    def _find_or_create_customer_partner(self):
        """Find/create the CLIENT partner (customer) by Upwork company name."""
        self.ensure_one()
        Partner = self.env['res.partner']
        name = (self.assignment_company_name or '').strip()
        if not name:
            return Partner

        partner = Partner.search([
            ('name', '=ilike', name),
            ('company_id', 'in', [self.env.company.id, False]),
        ], limit=1) or Partner.search([
            ('name', 'ilike', name),
            ('company_id', 'in', [self.env.company.id, False]),
        ], limit=1)
        if not partner:
            partner = Partner.create({
                'name': name,
                'is_company': True,
                'customer_rank': 1,
                'company_id': self.env.company.id,
            })

        # Fill empty street / zip / country from extracted invoice data (if any),
        # for both found and newly-created partners.
        if self.extracted_client_address or self.extracted_client_zip \
                or self.extracted_client_country:
            self._write_partner_address(partner)
        return partner

    # ── Confidence + reconciliation ───────────────────────────────────────────

    def _check_customer_invoice(self, inv):
        """Authoritative data → light check: partner + line + invoice_date + ±5% amount."""
        self.ensure_one()
        if not inv.partner_id or not inv.invoice_line_ids or not inv.invoice_date:
            return False
        tx_amount = abs(self.transaction_amount_raw or 0)
        inv_amount = inv.amount_total
        if tx_amount and inv_amount:
            if abs(inv_amount - tx_amount) / tx_amount > 0.05:
                return False
        elif tx_amount and not inv_amount:
            return False
        return True

    def _auto_reconcile_customer_invoice(self):
        """Reconcile the posted customer invoice's receivable line against the
        Upwork Wallet inflow statement line (mirror of _auto_reconcile_bill)."""
        self.ensure_one()
        inv = self.customer_invoice_id
        stmt = self.statement_line_id
        if not inv or not stmt or inv.state != 'posted':
            return False
        inv_recv = inv.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled)
        if not inv_recv:
            return False
        try:
            widget = self.env['bank.rec.widget'].new({'st_line_id': stmt.id})
            widget._ensure_loaded_lines()
            widget._action_add_new_amls(inv_recv[:1])
            widget._action_validate()
            return True
        except Exception as e:
            _logger.warning(
                "Auto-reconcile failed for customer invoice %s / statement line %s: %s",
                inv.id, stmt.id, e)
            return False

    # ── One-click dispatcher ────────────────────────────────────────────────────

    def action_create_accounting_documents(self):
        """Bulk: for each selected transaction create the right accounting document
        by its posting mode (customer invoice / vendor bill / customer or vendor
        credit note) and reconcile against the wallet line. `gl`-mode and PDF-less
        rows are skipped.

        Run AFTER 'Inject to Accounting' and AFTER uploading the split Upwork PDFs.
        """
        ci = self.filtered(lambda r: r.injection_mode == 'customer_invoice')
        cr = self.filtered(lambda r: r.injection_mode == 'customer_refund')
        vb = self.filtered(lambda r: r.injection_mode == 'vendor_bill')
        vr = self.filtered(lambda r: r.injection_mode == 'vendor_refund')
        if ci:
            ci._process_customer_invoice_batch(auto_post=True, auto_reconcile=True)
        if cr:
            cr._process_refund_batch('customer')
        if vb:
            vb.action_create_vendor_bill()
        if vr:
            vr._process_refund_batch('vendor')
        msg = _('Processed %(ci)d customer invoices, %(cr)d customer credit notes, '
                '%(vb)d vendor bills, %(vr)d vendor credit notes. '
                'gl and PDF-less transactions were skipped.',
                ci=len(ci), cr=len(cr), vb=len(vb), vr=len(vr))
        return self._usa_notify(
            _('Create Accounting Documents'), msg,
            'success' if (ci or cr or vb or vr) else 'info', False)

    def action_inject_and_create_documents(self):
        """One-click end-to-end: inject the bank statement lines, then create the
        right accounting document per posting mode and reconcile — in one pass.
        Upload the split Upwork PDFs first so the documents have their pages."""
        self.action_inject_to_accounting()
        self.action_create_accounting_documents()
        return self._usa_notify(
            _('Inject & Create Docs & Reconcile'),
            _('Processed %d transaction(s): injected the wallet lines, created the '
              'mapped invoices/bills/credit notes and reconciled. PDF-less rows had '
              'their bank line injected only.') % len(self),
            'success', False)

    # ── helper ──────────────────────────────────────────────────────────────────

    def _usa_notify(self, title, message, ntype, sticky):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': title, 'message': message,
                       'type': ntype, 'sticky': sticky},
        }
