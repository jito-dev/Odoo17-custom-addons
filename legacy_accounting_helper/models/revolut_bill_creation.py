# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RevolutTransactionBillCreation(models.Model):
    _inherit = 'revolut.transaction'

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
                # Post the bill if still draft
                if bill.state == 'draft':
                    bill.action_post()
                    posted += 1

                if bill.state == 'posted' and rec._auto_reconcile_bill():
                    reconciled += 1
                else:
                    errors.append(
                        rec.description or rec.merchant_name or rec.revolut_id
                    )
            except Exception as e:
                errors.append(f'{rec.revolut_id}: {str(e)[:100]}')
                _logger.exception(
                    "Error reconciling bill for revolut TX %s", rec.revolut_id,
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

    # ── Batch processing ──────────────────────────────────────────────

    def _process_vendor_bill_batch(self, auto_post=True, auto_reconcile=True, title=''):
        """Shared batch logic for bill creation actions.

        Args:
            auto_post: If True, auto-post bills that pass confidence check.
            auto_reconcile: If True, auto-reconcile posted bills with statement lines.
            title: Notification title.
        """
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

            if not rec.invoice_attachment_ids:
                skipped += 1
                continue

            try:
                bill = rec._create_vendor_bill_from_attachment()
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
                            "Auto-post failed for bill %s (revolut TX %s): %s",
                            bill.id, rec.revolut_id, e,
                        )
                        draft_review.append(
                            rec.description or rec.merchant_name or rec.revolut_id
                        )
                elif auto_post:
                    draft_review.append(
                        rec.description or rec.merchant_name or rec.revolut_id
                    )

            except Exception as e:
                errors.append(f'{rec.revolut_id}: {str(e)[:100]}')
                _logger.exception(
                    "Error creating vendor bill for revolut TX %s", rec.revolut_id,
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

    def _create_vendor_bill_from_attachment(self):
        """Create a draft vendor bill and copy the first PDF/image attachment.

        Returns the created account.move or False.
        """
        self.ensure_one()

        # Find the first suitable attachment (PDF preferred, then image)
        attachment = self._find_best_invoice_attachment()
        if not attachment:
            return False

        # Pre-seed partner from existing Revolut matching
        partner = False
        if not self.transfer_between_accounts:
            partner = self._find_partner_for_transaction()

        # Find the default purchase journal
        journal = self.env['account.journal'].search([
            ('type', '=', 'purchase'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not journal:
            raise UserError(_(
                "No purchase journal found for company %s. "
                "Please create one first.",
                self.company_id.name,
            ))

        # Create the vendor bill WITHOUT invoice_date or ref — let AI extract
        # the real values from the PDF. Fallbacks are set after AI extraction.
        bill_vals = {
            'move_type': 'in_invoice',
            'journal_id': journal.id,
            'revolut_transaction_id': self.id,
        }
        if partner:
            bill_vals['partner_id'] = partner.id

        bill = self.env['account.move'].create(bill_vals)

        # Create a fresh attachment on the bill (copy datas explicitly)
        new_attachment = self.env['ir.attachment'].create({
            'name': attachment.name,
            'datas': attachment.datas,
            'mimetype': attachment.mimetype,
            'res_model': 'account.move',
            'res_id': bill.id,
        })

        # Post the attachment via message_post so it's visible in the chatter
        bill.with_context(no_new_invoice=True).message_post(
            attachment_ids=[new_attachment.id],
            body=_("Invoice attached from Revolut transaction %s", self.revolut_id),
        )

        # Set as main attachment — this triggers AI extraction if auto_send
        new_attachment.register_as_main_attachment(force=True)

        # If AI extraction didn't auto-trigger (mode != auto_send), force it
        if (
            bill.ai_extract_state == 'no_extract'
            and bill.message_main_attachment_id
            and bill.state == 'draft'
        ):
            bill._ai_extract_invoice_data()

        # If AI still didn't set a partner, try matching by merchant name,
        # then create a new vendor partner as last resort
        if not bill.partner_id:
            partner = self._find_or_create_vendor_partner(bill)
            if partner:
                bill.partner_id = partner

        # Fallback ref: if AI didn't extract an invoice number, use TX data
        if not bill.ref:
            bill.ref = self.description or self.merchant_name or self.reference or self.revolut_id

        # Fallback dates: if AI didn't extract dates, use TX settlement date
        if not bill.invoice_date:
            bill.invoice_date = (
                self.settlement_date_local
                or self.settlement_date
                or fields.Date.context_today(self)
            )

        # Fallback payment reference
        if not bill.payment_reference:
            parts = [self.merchant_name or self.description or '']
            if bill.ref:
                parts.append(bill.ref)
            bill.payment_reference = ' - '.join(filter(None, parts)) or self.revolut_id

        # Link back
        self.vendor_bill_id = bill.id

        return bill

    def _find_or_create_vendor_partner(self, bill):
        """Find an existing vendor partner or create a new one.

        Search priority:
        1. AI-extracted vendor name/VAT (already attempted by AI, but try broader)
        2. Revolut merchant_name
        3. Revolut counterparty IBAN
        If all searches fail, create a new vendor partner.
        """
        self.ensure_one()
        Partner = self.env['res.partner']

        # Collect candidate names: AI-extracted ref on the bill, then merchant_name
        candidate_names = []
        if bill.ref:
            candidate_names.append(bill.ref)
        if self.merchant_name:
            candidate_names.append(self.merchant_name.strip())
        if self.description and self.description != bill.ref:
            candidate_names.append(self.description.strip())

        for name in candidate_names:
            if not name:
                continue

            # Exact (case-insensitive)
            partner = Partner.search([
                ('name', '=ilike', name),
                ('company_id', 'in', [self.company_id.id, False]),
            ], limit=1)
            if partner:
                return partner

            # Contains
            partner = Partner.search([
                ('name', 'ilike', name),
                ('company_id', 'in', [self.company_id.id, False]),
            ], limit=1)
            if partner:
                return partner

        # Reverse contains: partner name is contained in merchant/description
        # e.g. merchant "SLACK TECHNOLOGIES INC" matches partner "Slack"
        if candidate_names:
            company_partners = Partner.search([
                ('is_company', '=', True),
                ('company_id', 'in', [self.company_id.id, False]),
            ], limit=200)
            for name in candidate_names:
                if not name:
                    continue
                name_lower = name.lower()
                for p in company_partners:
                    if p.name and p.name.lower() in name_lower:
                        return p

        # Counterparty IBAN match
        for leg in self.leg_ids:
            if leg.counterparty_account_id:
                bank = self.env['res.partner.bank'].search(
                    [('acc_number', 'ilike', leg.counterparty_account_id)],
                    limit=1,
                )
                if bank and bank.partner_id:
                    return bank.partner_id

        # Nothing found — create a new vendor partner
        vendor_name = self.merchant_name or self.description or self.reference
        if not vendor_name:
            return False

        vendor_name = vendor_name.strip()
        _logger.info(
            "Creating new vendor partner '%s' from Revolut TX %s",
            vendor_name, self.revolut_id,
        )
        new_partner = Partner.create({
            'name': vendor_name,
            'is_company': True,
            'supplier_rank': 1,
            'company_id': self.company_id.id,
        })
        return new_partner

    def _find_best_invoice_attachment(self):
        """Find the best attachment for bill creation (PDF first, then image)."""
        self.ensure_one()
        if not self.invoice_attachment_ids:
            return False

        # Prefer PDF
        for att in self.invoice_attachment_ids:
            if att.mimetype == 'application/pdf':
                return att

        # Fallback to image
        for att in self.invoice_attachment_ids:
            if att.mimetype and att.mimetype.startswith('image/'):
                return att

        # Last resort: first attachment
        return self.invoice_attachment_ids[0]

    # ── Confidence check ─────────────────────────────────────────────

    def _check_bill_confidence(self, bill):
        """Return True if the AI-populated bill is high-confidence enough to auto-post."""
        self.ensure_one()

        # AI extraction must have completed successfully
        if bill.ai_extract_state != 'done':
            return False

        # Must have a vendor
        if not bill.partner_id:
            return False

        # Must have invoice lines
        if not bill.invoice_line_ids:
            return False

        # Must have an invoice date
        if not bill.invoice_date:
            return False

        # Amount sanity: bill total should be close to TX amount (±5%)
        tx_amount = abs(self.amount)
        bill_amount = bill.amount_total
        if tx_amount and bill_amount:
            diff_pct = abs(bill_amount - tx_amount) / tx_amount
            if diff_pct > 0.05:
                return False
        elif tx_amount and not bill_amount:
            # Bill has zero amount but TX doesn't
            return False

        return True

    # ── Auto-reconciliation ──────────────────────────────────────────

    def _auto_reconcile_bill(self):
        """Reconcile the posted vendor bill with the bank statement line
        using Odoo's bank.rec.widget (the same mechanism as the UI).

        The widget rewrites the statement move to replace the suspense line
        with the bill's payable account, then reconciles both sides.

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
            # Use the bank reconciliation widget programmatically
            widget = self.env['bank.rec.widget'].new({
                'st_line_id': stmt_line.id,
            })
            widget._ensure_loaded_lines()

            # Add the bill's payable line as a match
            widget._action_add_new_amls(bill_payable[:1])

            # Validate — this rewrites the statement move and reconciles
            widget._action_validate()
            return True
        except Exception as e:
            _logger.warning(
                "Auto-reconcile failed for bill %s / statement line %s: %s",
                bill.id, stmt_line.id, e,
            )
            return False
