# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class UsaTransactionBillCreation(models.Model):
    _inherit = 'usa.transaction'

    vendor_bill_id = fields.Many2one(
        'account.move', string='Vendor Bill',
        readonly=True, copy=False, ondelete='set null',
        domain="[('move_type', '=', 'in_invoice')]",
    )
    has_vendor_bill = fields.Boolean(
        string='Has Vendor Bill',
        compute='_compute_has_vendor_bill',
    )
    is_bill_reconciled = fields.Boolean(
        string='Bill Reconciled',
        compute='_compute_bill_reconciled',
    )

    @api.depends('vendor_bill_id')
    def _compute_has_vendor_bill(self):
        for rec in self:
            rec.has_vendor_bill = bool(rec.vendor_bill_id)

    @api.depends('statement_line_id.is_reconciled')
    def _compute_bill_reconciled(self):
        for rec in self:
            rec.is_bill_reconciled = (
                rec.statement_line_id.is_reconciled
                if rec.statement_line_id
                else False
            )

    # ── Actions ──────────────────────────────────────────────────────

    def action_create_vendor_bill(self):
        """Full pipeline: create bill, AI extract, create vendor,
        auto-post if confident, auto-reconcile."""
        return self._process_vendor_bill_batch(
            auto_post=True, auto_reconcile=True,
            title=_('Create Bills & Reconcile'),
        )

    def action_create_draft_vendor_bill(self):
        """Create draft bill with AI extraction and vendor matching/creation.
        No auto-post, no auto-reconcile — bill stays in draft."""
        return self._process_vendor_bill_batch(
            auto_post=False, auto_reconcile=False,
            title=_('Create Draft Bills'),
        )

    def action_reconcile_vendor_bill(self):
        """Post the vendor bill (if draft) and reconcile with the statement line."""
        posted = 0
        reconciled = 0
        skipped = 0
        errors = []

        for rec in self:
            bill = rec.vendor_bill_id
            stmt_line = rec.statement_line_id

            if not bill or not stmt_line:
                skipped += 1
                continue

            if stmt_line.is_reconciled:
                skipped += 1
                continue

            try:
                if bill.state == 'draft':
                    bill.action_post()
                    posted += 1

                if bill.state == 'posted' and rec._auto_reconcile_bill():
                    reconciled += 1
                else:
                    errors.append(
                        rec.description or rec.record_id
                    )
            except Exception as e:
                errors.append(f'{rec.record_id}: {str(e)[:100]}')
                _logger.exception(
                    "Error reconciling bill for Upwork TX %s", rec.record_id,
                )

        total = len(self)
        msg_parts = []
        if posted:
            msg_parts.append(f'{posted} bills posted.')
        if reconciled:
            msg_parts.append(f'{reconciled}/{total} reconciled.')
        if skipped:
            msg_parts.append(f'{skipped} skipped.')
        if errors:
            msg_parts.append(f'{len(errors)} errors: ' + '; '.join(errors[:3]))

        notif_type = 'success' if reconciled and not errors else (
            'warning' if errors else 'info'
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reconcile Bills'),
                'message': ' '.join(msg_parts) or _('Nothing to reconcile.'),
                'type': notif_type,
                'sticky': bool(errors),
            },
        }

    def action_open_vendor_bill(self):
        """Open the linked vendor bill in a form view."""
        self.ensure_one()
        if not self.vendor_bill_id:
            raise UserError(_("No vendor bill linked to this transaction."))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.vendor_bill_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_fix_bill_vendor(self):
        """Repair already-created vendor bills saved with the client as vendor:
        set the vendor to Upwork (reset to draft / re-post as needed). Reconciled
        bills are skipped — unreconcile and fix those manually."""
        vendor = self._get_upwork_vendor()
        fixed = skipped = errors = 0
        for rec in self:
            bill = rec.vendor_bill_id
            if not bill or bill.partner_id.id == vendor.id:
                skipped += 1
                continue
            if rec.is_bill_reconciled:
                skipped += 1
                continue
            try:
                was_posted = bill.state == 'posted'
                if was_posted:
                    bill.button_draft()
                bill.partner_id = vendor.id
                if was_posted:
                    bill.action_post()
                fixed += 1
            except Exception as e:
                errors += 1
                _logger.warning("Could not fix vendor on bill %s: %s", bill.id, e)
        return self._usa_notify(
            _('Fix Bill Vendor'),
            _('%(f)d bills set to Upwork, %(s)d skipped, %(e)d errors.',
              f=fixed, s=skipped, e=errors),
            'success' if fixed and not errors else 'warning', bool(errors))

    # ── Batch processing ──────────────────────────────────────────────

    def _process_vendor_bill_batch(self, auto_post=True, auto_reconcile=True, title=''):
        """Shared batch logic for bill creation actions."""
        created = 0
        skipped = 0
        posted = 0
        reconciled = 0
        draft_review = []
        errors = []

        for rec in self:
            if rec.vendor_bill_id:
                skipped += 1
                continue

            # Only bill transactions whose posting mode is vendor_bill — never
            # a revenue/refund tx that happens to carry a split PDF page.
            if rec.injection_mode != 'vendor_bill':
                skipped += 1
                continue

            if not rec.upwork_invoice_pdf:
                skipped += 1
                continue

            try:
                bill = rec._create_vendor_bill_from_upwork_invoice()
                if not bill:
                    skipped += 1
                    continue

                created += 1

                if auto_post and rec._check_bill_confidence(bill):
                    try:
                        bill.action_post()
                        posted += 1

                        if auto_reconcile and rec.statement_line_id:
                            if rec._auto_reconcile_bill():
                                reconciled += 1
                    except Exception as e:
                        _logger.warning(
                            "Auto-post failed for bill %s (Upwork TX %s): %s",
                            bill.id, rec.record_id, e,
                        )
                        draft_review.append(rec.description or rec.record_id)
                elif auto_post:
                    draft_review.append(rec.description or rec.record_id)

            except Exception as e:
                errors.append(f'{rec.record_id}: {str(e)[:100]}')
                _logger.exception(
                    "Error creating vendor bill for Upwork TX %s", rec.record_id,
                )

        total = len(self)
        msg_parts = [f'{created}/{total} vendor bills created.']
        if posted:
            msg_parts.append(f'{posted} auto-posted.')
        if reconciled:
            msg_parts.append(f'{reconciled} auto-reconciled.')
        if skipped:
            msg_parts.append(f'{skipped} skipped.')
        if draft_review:
            msg_parts.append(f'{len(draft_review)} left as draft for review.')
        if errors:
            msg_parts.append(f'{len(errors)} errors: ' + '; '.join(errors[:3]))

        notif_type = 'success' if created and not errors else (
            'warning' if errors else 'info'
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title or _('Create Vendor Bills'),
                'message': ' '.join(msg_parts),
                'type': notif_type,
                'sticky': bool(errors or draft_review),
            },
        }

    # ── Bill creation logic ──────────────────────────────────────────

    def _create_vendor_bill_from_upwork_invoice(self):
        """Create a draft vendor bill from the Upwork invoice PDF.

        Returns the created account.move or False.
        """
        self.ensure_one()

        if not self.upwork_invoice_pdf:
            return False

        # The vendor of an Upwork fee bill is Upwork, not the client.
        partner = self._get_upwork_vendor()

        # Get the purchase journal
        journal = self.env['account.journal'].search([
            ('type', '=', 'purchase'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not journal:
            raise UserError(_(
                "No purchase journal found. Please create one first.",
            ))

        bill_vals = {
            'move_type': 'in_invoice',
            'journal_id': journal.id,
        }
        if partner:
            bill_vals['partner_id'] = partner.id

        bill = self.env['account.move'].create(bill_vals)

        # Convert Binary field → ir.attachment and attach to bill
        filename = self.upwork_invoice_filename or 'upwork_invoice.pdf'
        # Read without bin_size context to get actual binary data
        pdf_data = self.with_context(bin_size=False).upwork_invoice_pdf

        new_attachment = self.env['ir.attachment'].create({
            'name': filename,
            'datas': pdf_data,
            'mimetype': 'application/pdf',
            'res_model': 'account.move',
            'res_id': bill.id,
        })

        # Post attachment in chatter so it's visible
        bill.with_context(no_new_invoice=True).message_post(
            attachment_ids=[new_attachment.id],
            body=_("Invoice attached from Upwork transaction %s", self.record_id),
        )

        # Register as main attachment — may trigger AI extraction if auto_send
        new_attachment.register_as_main_attachment(force=True)

        # Force AI extraction if it didn't auto-trigger
        if (
            bill.ai_extract_state == 'no_extract'
            and bill.message_main_attachment_id
            and bill.state == 'draft'
        ):
            bill._ai_extract_invoice_data()

        # The vendor is ALWAYS Upwork — force it so a client pre-seed or an AI
        # mis-extraction (or AI being unavailable) can't leave the wrong vendor.
        bill.partner_id = self._get_upwork_vendor()

        # Post the expense to the mapped Upwork account (Service Fee → 600500,
        # Membership → 600510). The AI extraction defaults invoice lines to the
        # company's generic expense account (600000), so override it here while
        # the bill is still draft.
        self._apply_mapped_expense_account(bill)

        # Fallback ref
        if not bill.ref:
            bill.ref = self.description or self.record_id

        # Accounting date — always Upwork's ledger (review-due) date, overriding any
        # date the AI extraction read from the PDF, so the bill matches the bank line
        # and the rest of the Upwork ledger.
        bill.invoice_date = self._get_accounting_date()

        # Fallback payment reference
        if not bill.payment_reference:
            parts = [self.assignment_company_name or self.description or '']
            if bill.ref:
                parts.append(bill.ref)
            bill.payment_reference = ' - '.join(filter(None, parts)) or self.record_id

        # Link back
        self.vendor_bill_id = bill.id

        return bill

    def _apply_mapped_expense_account(self, bill):
        """Force the bill's expense line(s) onto the account mapped for this tx
        (Service Fee → 600500, Membership → 600510), overriding the generic
        default expense account the AI extraction assigns. Draft bills only."""
        self.ensure_one()
        if not bill or bill.state != 'draft':
            return
        settings = self.env['usa.settings'].sudo()._get_singleton()
        account = settings._get_account_for_transaction(self)
        if not account:
            return
        lines = bill.invoice_line_ids.filtered(
            lambda l: l.display_type not in ('line_section', 'line_note')
            and l.account_id.id != account.id
        )
        if lines:
            lines.write({'account_id': account.id})

    def _find_or_create_vendor_partner(self, bill):
        """Find an existing vendor partner or create a new one.

        Search priority:
        1. Client company name from Upwork
        2. Description
        If all searches fail, create a new vendor partner.
        """
        self.ensure_one()
        Partner = self.env['res.partner']

        candidate_names = []
        if self.assignment_company_name:
            candidate_names.append(self.assignment_company_name.strip())
        if self.description:
            candidate_names.append(self.description.strip())

        for name in candidate_names:
            if not name:
                continue

            # Exact (case-insensitive)
            partner = Partner.search([
                ('name', '=ilike', name),
                ('company_id', 'in', [self.env.company.id, False]),
            ], limit=1)
            if partner:
                return partner

            # Contains
            partner = Partner.search([
                ('name', 'ilike', name),
                ('company_id', 'in', [self.env.company.id, False]),
            ], limit=1)
            if partner:
                return partner

        # Reverse contains: partner name is contained in description
        if candidate_names:
            company_partners = Partner.search([
                ('is_company', '=', True),
                ('company_id', 'in', [self.env.company.id, False]),
            ], limit=200)
            for name in candidate_names:
                if not name:
                    continue
                name_lower = name.lower()
                for p in company_partners:
                    if p.name and p.name.lower() in name_lower:
                        return p

        # Nothing found — create a new vendor partner
        vendor_name = self.assignment_company_name or self.description
        if not vendor_name:
            return False

        vendor_name = vendor_name.strip()
        _logger.info(
            "Creating new vendor partner '%s' from Upwork TX %s",
            vendor_name, self.record_id,
        )
        new_partner = Partner.create({
            'name': vendor_name,
            'is_company': True,
            'supplier_rank': 1,
            'company_id': self.env.company.id,
        })
        return new_partner

    # ── Confidence check ─────────────────────────────────────────────

    def _check_bill_confidence(self, bill):
        """Return True if the AI-populated bill is high-confidence enough to auto-post."""
        self.ensure_one()

        if bill.ai_extract_state != 'done':
            return False

        if not bill.partner_id:
            return False

        if not bill.invoice_line_ids:
            return False

        if not bill.invoice_date:
            return False

        # Amount sanity: bill total should be close to TX amount (±5%)
        tx_amount = abs(self.transaction_amount_raw or 0)
        bill_amount = bill.amount_total
        if tx_amount and bill_amount:
            diff_pct = abs(bill_amount - tx_amount) / tx_amount
            if diff_pct > 0.05:
                return False
        elif tx_amount and not bill_amount:
            return False

        return True

    # ── Auto-reconciliation ──────────────────────────────────────────

    def _auto_reconcile_bill(self):
        """Reconcile the posted vendor bill with the bank statement line
        using Odoo's bank.rec.widget.

        Returns True if reconciliation succeeded, False otherwise.
        """
        self.ensure_one()

        bill = self.vendor_bill_id
        stmt_line = self.statement_line_id

        if not bill or not stmt_line:
            return False

        if bill.state != 'posted':
            return False

        # Find the bill's payable line (unreconciled)
        bill_payable = bill.line_ids.filtered(
            lambda l: l.account_id.account_type == 'liability_payable'
            and not l.reconciled
        )
        if not bill_payable:
            return False

        try:
            widget = self.env['bank.rec.widget'].new({
                'st_line_id': stmt_line.id,
            })
            widget._ensure_loaded_lines()
            widget._action_add_new_amls(bill_payable[:1])
            widget._action_validate()
            return True
        except Exception as e:
            _logger.warning(
                "Auto-reconcile failed for bill %s / statement line %s: %s",
                bill.id, stmt_line.id, e,
            )
            return False
