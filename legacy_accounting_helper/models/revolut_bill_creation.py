# -*- coding: utf-8 -*-

import logging
import re

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
    # Inline manual picker — stage an unpaid vendor bill, then attach it with the
    # button (staging only; cleared right after attach). Domain mirrors the
    # 'Match & Attach' wizard's notion of an owable bill (see _find_matching_bill).
    manual_bill_pick_id = fields.Many2one(
        'account.move', string='Attach Existing Bill',
        copy=False, ondelete='set null',
        domain="[('move_type', '=', 'in_invoice'),"
               " ('company_id', '=', company_id),"
               " ('state', 'in', ('draft', 'posted')),"
               " ('payment_state', 'in', ('not_paid', 'partial'))]",
        help="Pick an unpaid vendor bill by its number (e.g. BILL/2026/02/0026) "
             "and click 'Attach Bill'. Only unpaid/partially-paid bills of this "
             "company are listed.",
    )
    has_vendor_bill = fields.Boolean(
        string='Has Vendor Bill',
        compute='_compute_has_vendor_bill',
    )
    is_bill_reconciled = fields.Boolean(
        string='Bill Reconciled',
        compute='_compute_bill_reconciled', store=True,
    )
    vendor_bill_preview_html = fields.Html(
        string='Vendor Bill Preview', sanitize=False,
        compute='_compute_vendor_bill_preview',
    )
    accounting_stage = fields.Selection(
        [('to_inject', 'To inject'),
         ('injected', 'Injected'),
         ('needs_bill', 'Needs bill/invoice'),
         ('bill_draft', 'Bill/invoice draft'),
         ('to_reconcile', 'To reconcile'),
         ('reconciled', 'Reconciled')],
        string='Accounting Stage', compute='_compute_accounting_stage', store=True,
        help='Pipeline: inject the bank tx → attach/create a bill or customer '
             'invoice → reconcile.')

    _FCF_TYPES = ('fcf_buy', 'fcf_sell', 'fcf_interest', 'fcf_fee')
    # Types that never need a vendor bill (booked directly on the bank line).
    _NO_BILL_TYPES = _FCF_TYPES + ('fee',)

    @api.depends('statement_line_id', 'vendor_bill_id', 'vendor_bill_id.state',
                 'customer_invoice_id', 'customer_invoice_id.state',
                 'is_bill_reconciled', 'transaction_type', 'transfer_between_accounts',
                 'document_status')
    def _compute_accounting_stage(self):
        for rec in self:
            # An outgoing tx carries a vendor bill; an incoming tx a customer
            # invoice. Both are account.move with a state, and the stage follows
            # the same draft → posted → reconciled path either way.
            doc = rec.vendor_bill_id or rec.customer_invoice_id
            if not rec.statement_line_id:
                rec.accounting_stage = 'to_inject'
            elif doc:
                if rec.is_bill_reconciled:
                    rec.accounting_stage = 'reconciled'
                elif doc.state == 'posted':
                    rec.accounting_stage = 'to_reconcile'
                else:
                    rec.accounting_stage = 'bill_draft'
            elif rec.document_status == 'lost':
                # Lost document → booked to Disallowable on reconcile (no bill).
                # Reconciled once the suspense is cleared; else awaiting that step.
                rec.accounting_stage = 'reconciled' if rec.is_bill_reconciled else 'needs_bill'
            elif rec.transfer_between_accounts or (rec.transaction_type or '') in rec._NO_BILL_TYPES:
                rec.accounting_stage = 'injected'   # internal / fee — no bill needed
            else:
                rec.accounting_stage = 'needs_bill'

    @api.depends('vendor_bill_id')
    def _compute_has_vendor_bill(self):
        for rec in self:
            rec.has_vendor_bill = bool(rec.vendor_bill_id)

    @api.depends('vendor_bill_id', 'vendor_bill_id.message_main_attachment_id')
    def _compute_vendor_bill_preview(self):
        for rec in self:
            html = ''
            bill = rec.vendor_bill_id
            att = bill.message_main_attachment_id if bill else False
            if bill and not att:
                html = '<span class="text-muted">Bill linked — no document attached to it.</span>'
            elif att:
                mt = (att.mimetype or '').lower()
                if mt.startswith('image/'):
                    html = (
                        '<img src="/web/image/ir.attachment/%s/datas" '
                        'style="max-width:100%%;max-height:340px;object-fit:contain;'
                        'border:1px solid #dee2e6;border-radius:4px;"/>' % att.id)
                elif mt == 'application/pdf':
                    # Click-to-open, NOT an auto-loading <iframe>: an inline PDF
                    # embedded on form load is served with a restrictive CSP and
                    # Chrome downloads it instead of previewing. Matches the
                    # module's own convention (action_open_receipt_pdf).
                    html = (
                        '<a href="/web/content/%s?download=false" target="_blank" '
                        'class="btn btn-secondary btn-sm"><i class="fa fa-file-pdf-o me-1"></i>'
                        'Open bill PDF</a>' % att.id)
                else:
                    html = (
                        '<a href="/web/content/%s?download=false" target="_blank" '
                        'class="btn btn-secondary btn-sm"><i class="fa fa-file-o me-1"></i>'
                        'Open document</a>' % att.id)
            rec.vendor_bill_preview_html = html

    @api.depends('statement_line_id.is_reconciled')
    def _compute_bill_reconciled(self):
        for rec in self:
            rec.is_bill_reconciled = (
                rec.statement_line_id.is_reconciled
                if rec.statement_line_id
                else False
            )

    def action_unlink_vendor_bill(self):
        """Unlink the vendor bill from the selected transactions: clear
        vendor_bill_id, drop the bill's auto-attached document from receipts, and
        unreconcile the statement line if it was reconciled with the bill."""
        cleared = unreconciled = skipped = 0
        for rec in self:
            bill = rec.vendor_bill_id
            if not bill:
                skipped += 1
                continue
            # Unreconcile the statement line ↔ bill if currently reconciled.
            if rec.statement_line_id and rec.statement_line_id.is_reconciled:
                try:
                    for ml in rec.statement_line_id.move_id.line_ids:
                        (ml.matched_debit_ids + ml.matched_credit_ids).unlink()
                    unreconciled += 1
                except Exception as e:  # noqa: BLE001
                    _logger.warning("Unlink bill: could not unreconcile tx %s: %s", rec.id, e)
            # Remove the bill's main document we linked as a receipt (keep the file).
            main_att = bill.message_main_attachment_id
            if main_att and main_att in rec.invoice_attachment_ids:
                rec.invoice_attachment_ids = [(3, main_att.id)]
            rec.vendor_bill_id = False
            cleared += 1
        msg = _('%s bill(s) unlinked, %s unreconciled, %s skipped.') % (
            cleared, unreconciled, skipped)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Unlink Vendor Bill'),
                'message': msg,
                'type': 'warning' if not cleared else 'success',
                'sticky': False,
            },
        }

    def action_attach_manual_bill(self):
        """Attach the manually-picked vendor bill to this transaction.

        The per-record counterpart of the batch 'Match & Attach Vendor Bills'
        wizard: link the chosen bill as ``vendor_bill_id`` (a reference, not a
        copy) and surface its main document as a receipt — same effect as
        ``revolut.bill.link.wizard.action_attach``. Reconciliation stays a
        separate step ('Reconcile injected bill & tx'). Blocks re-using a bill
        already linked to another transaction to avoid double reconciliation."""
        self.ensure_one()
        bill = self.manual_bill_pick_id
        if not bill:
            raise UserError(_("Pick a vendor bill to attach first."))
        if bill.move_type != 'in_invoice':
            raise UserError(_("Only vendor bills can be attached here."))
        other = self.search(
            [('vendor_bill_id', '=', bill.id), ('id', '!=', self.id)], limit=1)
        if other:
            raise UserError(_(
                "Bill %(bill)s is already attached to transaction %(tx)s. "
                "Unlink it there first.",
                bill=bill.display_name,
                tx=other.display_name or other.revolut_id,
            ))
        self.vendor_bill_id = bill.id
        # Link the bill's main document as a receipt (counter + preview), matching
        # the wizard — keep the file, just reference it.
        main_att = bill.message_main_attachment_id
        if main_att and main_att not in self.invoice_attachment_ids:
            self.invoice_attachment_ids = [(4, main_att.id)]
        self.manual_bill_pick_id = False
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Vendor Bill Attached'),
                'message': _(
                    'Linked %s. Reconcile via "Reconcile injected bill & tx".',
                    bill.display_name),
                'type': 'success',
                'sticky': False,
                # Reload the form so the section flips to the linked/preview state.
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    # ── Actions ──────────────────────────────────────────────────────

    def action_open_rule_suggest_wizard(self):
        """Open the 'Suggest Injection Rules (AI)' wizard for the selected
        transactions: pick a GL account, AI proposes routing rules, review, then
        save them into Injection Rules."""
        if not self:
            raise UserError(_("Select at least one transaction first."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Suggest Injection Rules (AI)'),
            'res_model': 'revolut.rule.suggest.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_transaction_ids': [(6, 0, self.ids)]},
        }

    def action_open_bill_match_wizard(self):
        """Open the 'Upload & Match Bills' wizard for the selected transactions:
        upload manually-downloaded bills (PDF/image/DOCX), let AI extract + match
        them to these transactions, then attach each confirmed bill."""
        if not self:
            raise UserError(_("Select at least one transaction first."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Upload & Match Bills'),
            'res_model': 'revolut.bill.match.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_transaction_ids': [(6, 0, self.ids)]},
        }

    def action_open_bill_link_wizard(self):
        """Open the 'Match & Attach Vendor Bills' wizard for the selected
        transactions: find existing Odoo vendor bills (by reference/amount, else
        name/amount/date), review, then link them so injection reconciles."""
        if not self:
            raise UserError(_("Select at least one transaction first."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Match & Attach Vendor Bills'),
            'res_model': 'revolut.bill.link.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_transaction_ids': [(6, 0, self.ids)]},
        }

    def _find_matching_bill(self):
        """Find the best existing vendor bill (account.move, in_invoice) for this
        transaction. Returns (bill, confidence, reason); empty recordset if none.
        Reference(UID)+amount is decisive; else partner-name+amount+date."""
        self.ensure_one()
        Move = self.env['account.move']
        amount = abs(self.amount or 0.0) or abs(self.bill_amount or 0.0)
        if amount <= 0:
            return Move, 'none', _('No amount to match against.')
        tol = max(0.02, amount * 0.01)  # 1% or 2 cents — absorbs FX/rounding

        linked = self.search([('vendor_bill_id', '!=', False)]).mapped('vendor_bill_id').ids
        domain = [
            ('move_type', '=', 'in_invoice'),
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
            return Move, 'none', _('No unmatched vendor bill near %.2f.', amount)

        # 1) Reference (UID) pass — the bill ref appears in the tx reference/description.
        hay_ref = ' '.join(filter(None, [self.reference, self.description])).lower()
        for bill in candidates:
            uid = (bill.ref or '').strip().lower()
            if uid and len(uid) >= 4 and uid in hay_ref:
                return bill, 'high', _('Reference "%s" matches; amount %.2f.', bill.ref, amount)

        # 2) Name + date fallback.
        hay_name = ' '.join(filter(None, [self.description, self.merchant_name])).lower()
        td = self.settlement_date_local or self.settlement_date
        best_low = Move
        for bill in candidates:
            tokens = [t for t in re.split(r'\W+', (bill.partner_id.name or '').lower()) if len(t) > 2]
            overlap = [t for t in tokens if t in hay_name]
            days = abs((bill.invoice_date - td).days) if (bill.invoice_date and td) else None
            if overlap and days is not None and days <= 14:
                return bill, 'medium', _('Name "%s" + amount %.2f + date ±%sd.',
                                         bill.partner_id.name, amount, days)
            if overlap and not best_low:
                best_low = bill
        if best_low:
            return best_low, 'low', _('Name "%s" + amount %.2f (date not close).',
                                      best_low.partner_id.name, amount)
        if len(candidates) == 1:
            return candidates, 'low', _('Only one unmatched bill near %.2f.', amount)
        return Move, 'none', _('%s bills near %.2f; no reference/name match.', len(candidates), amount)

    def action_create_vendor_bill(self):
        """Inject attached Bill: create a DRAFT vendor bill from the tx's receipt
        document (Gmail / Revolut / manual upload), with the Injection-Rule expense
        account + Data Source analytic. AI fills vendor/amount/date. No posting and
        no reconcile — use 'Reconcile injected bill & tx'. Txs that already have a
        bill (created or attached) are skipped."""
        return self._process_vendor_bill_batch(
            auto_post=False, auto_reconcile=False,
            title=_('Inject attached Bill'),
        )

    def action_reconcile_vendor_bill(self):
        """Post the vendor bill (if draft) and reconcile with the statement line.
        For transactions whose document status is 'Lost' and that have no bill, the
        suspense bank line is booked straight to the Disallowable expenses account
        instead (non-deductible, no input VAT) — no bill needed."""
        posted = 0
        reconciled = 0
        disallowed = 0
        skipped = 0
        errors = []

        for rec in self:
            bill = rec.vendor_bill_id
            stmt_line = rec.statement_line_id

            if not stmt_line:
                skipped += 1
                continue
            if stmt_line.is_reconciled:
                skipped += 1
                continue

            label = rec.merchant_name or rec.description or rec.revolut_id

            # Lost-document path: book the suspense line to Disallowable expenses.
            if rec.document_status == 'lost' and not bill:
                try:
                    with self.env.cr.savepoint():
                        ok = rec._post_lost_to_disallowable()
                    if ok:
                        disallowed += 1
                    else:
                        errors.append(f'{label}: nothing in suspense to book as disallowable')
                except Exception as e:  # noqa: BLE001
                    errors.append(f'{label}: {str(e).strip().splitlines()[0][:200] if str(e).strip() else type(e).__name__}')
                    _logger.exception("Disallowable posting failed for revolut TX %s", rec.revolut_id)
                continue

            if not bill:
                skipped += 1
                continue

            try:
                # Post the bill if still draft
                if bill.state == 'draft':
                    bill.action_post()
                    posted += 1

                if bill.state != 'posted':
                    errors.append(f'{label}: bill is not posted')
                else:
                    ok, reason = rec._auto_reconcile_bill()
                    if ok:
                        reconciled += 1
                    else:
                        errors.append(f'{label}: {reason or "could not reconcile"}')
            except Exception as e:
                errors.append(f'{label}: {str(e).strip().splitlines()[0][:200] if str(e).strip() else type(e).__name__}')
                _logger.exception(
                    "Error reconciling bill for revolut TX %s", rec.revolut_id,
                )

        total = len(self)
        msg_parts = []
        if posted:
            msg_parts.append(f'{posted} bills posted.')
        if reconciled:
            msg_parts.append(f'{reconciled}/{total} reconciled.')
        if disallowed:
            msg_parts.append(f'{disallowed} posted to Disallowable (lost document).')
        if skipped:
            msg_parts.append(f'{skipped} skipped.')
        if errors:
            msg_parts.append(f'{len(errors)} errors: ' + '; '.join(errors[:3]))

        notif_type = 'success' if (reconciled or disallowed) and not errors else (
            'warning' if errors else 'info'
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reconcile injected bill & tx'),
                'message': ' '.join(msg_parts) or _('Nothing to reconcile.'),
                'type': notif_type,
                'sticky': bool(errors),
            },
        }

    def action_unreconcile_bill(self):
        """Reverse of 'Reconcile injected bill & tx': remove the reconciliation
        between the bank statement line and the bill, keeping the link and the bill."""
        done = skipped = 0
        for rec in self:
            stmt_line = rec.statement_line_id
            if not rec.vendor_bill_id or not stmt_line or not stmt_line.is_reconciled:
                skipped += 1
                continue
            try:
                for ml in stmt_line.move_id.line_ids:
                    (ml.matched_debit_ids + ml.matched_credit_ids).unlink()
                done += 1
            except Exception as e:  # noqa: BLE001
                _logger.warning("Unreconcile failed for tx %s: %s", rec.id, e)
                skipped += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Unreconcile injected bill & tx'),
                'message': _('%s unreconciled, %s skipped.') % (done, skipped),
                'type': 'success' if done else 'warning',
                'sticky': False,
            },
        }

    def action_remove_attached_bill(self):
        """Reverse of 'Inject attached Bill': delete the Revolut-created vendor bill
        (unreconcile + draft first). Pre-existing Accounting bills (attached via
        Match & Attach) are skipped — use 'Unlink Vendor Bill' for those."""
        removed = skipped = errored = 0
        for rec in self:
            bill = rec.vendor_bill_id
            if not bill:
                skipped += 1
                continue
            # Only delete bills WE created from this tx's receipt.
            if bill.revolut_transaction_id != rec:
                skipped += 1
                continue
            try:
                if rec.statement_line_id and rec.statement_line_id.is_reconciled:
                    for ml in rec.statement_line_id.move_id.line_ids:
                        (ml.matched_debit_ids + ml.matched_credit_ids).unlink()
                main_att = bill.message_main_attachment_id
                if main_att and main_att in rec.invoice_attachment_ids:
                    rec.invoice_attachment_ids = [(3, main_att.id)]
                rec.vendor_bill_id = False
                if bill.state == 'posted':
                    bill.button_draft()
                bill.unlink()
                removed += 1
            except Exception as e:  # noqa: BLE001
                errored += 1
                _logger.warning("Remove attached bill failed for tx %s: %s", rec.id, e)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Remove attached Bill'),
                'message': _('%s bill(s) removed, %s skipped, %s errors.') % (
                    removed, skipped, errored),
                'type': 'warning' if (errored or not removed) else 'success',
                'sticky': bool(errored),
            },
        }

    def action_remove_all_from_accounting(self):
        """Full teardown: remove EVERYTHING this tx put into Odoo accounting —
        unreconcile, delete the Revolut-created bill (or unlink a pre-existing one,
        keeping it), and delete the injected bank statement line."""
        removed_lines = removed_bills = unlinked_bills = unreconciled = errors = 0
        for rec in self:
            try:
                stmt_line = rec.statement_line_id
                # 1) Unreconcile the bank line.
                if stmt_line and stmt_line.is_reconciled:
                    for ml in stmt_line.move_id.line_ids:
                        (ml.matched_debit_ids + ml.matched_credit_ids).unlink()
                    unreconciled += 1
                # 2) The bill — delete if WE created it, else just unlink (keep it).
                bill = rec.vendor_bill_id
                if bill:
                    main_att = bill.message_main_attachment_id
                    if main_att and main_att in rec.invoice_attachment_ids:
                        rec.invoice_attachment_ids = [(3, main_att.id)]
                    rec.vendor_bill_id = False
                    if bill.revolut_transaction_id == rec:
                        if bill.state == 'posted':
                            bill.button_draft()
                        bill.unlink()
                        removed_bills += 1
                    else:
                        unlinked_bills += 1
                # 3) The injected bank statement line.
                if stmt_line:
                    move = stmt_line.move_id
                    rec.statement_line_id = False
                    rec.fee_statement_line_id = False
                    rec.routed_account_id = False
                    rec.matched_rule_id = False
                    if move.state == 'posted':
                        move.button_draft()
                    move.unlink()
                    removed_lines += 1
            except Exception as e:  # noqa: BLE001
                errors += 1
                _logger.warning("Remove from accounting failed for tx %s: %s", rec.id, e)
        msg = _('Removed: %s bank line(s), %s bill(s) deleted, %s bill(s) unlinked, '
                '%s unreconciled, %s error(s).') % (
            removed_lines, removed_bills, unlinked_bills, unreconciled, errors)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Remove from Accounting'),
                'message': msg,
                'type': 'warning' if errors else 'success',
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
                            ok, _reason = rec._auto_reconcile_bill()
                            if ok:
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

        # Distribute the expense via the configured Injection Rules + tag the
        # "Data Source: Revolut Business API" analytic on the bill's expense lines.
        routed_account, routed_rule = self._route_to_gl_account()
        analytic = self._ensure_data_source_analytic(self.company_id)
        self.routed_account_id = routed_account.id if (routed_rule and routed_account) else False
        self.matched_rule_id = routed_rule.id if routed_rule else False

        rule_account = routed_account if (routed_rule and routed_account) else False
        # Always bill the transaction's OWN amount as a single gross line — AI
        # line breakdowns/totals are unreliable, and what the card was actually
        # charged is the company's expense. Cross-currency vs the bank line is
        # resolved as a normal FX difference at reconciliation.
        self._apply_tx_amount(bill, rule_account, analytic)

        # Link back
        self.vendor_bill_id = bill.id

        return bill

    def _apply_tx_amount(self, bill, rule_account, analytic):
        """Rewrite the bill to a SINGLE gross line (no tax) using the Revolut
        transaction's OWN amount & currency — the ORIGINAL (merchant) amount &
        currency when available (``bill_amount``/``bill_currency``), else the
        settled ``amount``/``currency``.

        AI line breakdowns and totals are unreliable; what the card was actually
        charged is the company's expense (split checks self-resolve, since the
        card is only charged the payer's share). When the original currency
        differs from the bank line's currency, reconciliation books the
        difference as a standard FX gain/loss.
        """
        self.ensure_one()
        # Prefer the original (merchant) amount/currency; fall back to settled.
        if self.bill_amount and self.bill_currency:
            amount = abs(self.bill_amount)
            ccy_name = self.bill_currency
        else:
            amount = abs(self.amount or 0.0)
            ccy_name = self.currency
        if not amount:
            return  # zero-amount tx (e.g. pre-auth) → leave AI lines as-is

        # Expense account: matched rule → AI's account → any expense account.
        ai_account = bill.invoice_line_ids[:1].account_id if bill.invoice_line_ids else False
        account = rule_account or ai_account
        if not account:
            account = self.env['account.account'].search([
                ('account_type', '=', 'expense'),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
        if not account:
            return  # can't build a valid line without an account

        currency = bill.currency_id
        if ccy_name:
            cur = self.env['res.currency'].search([('name', '=', ccy_name)], limit=1)
            if cur:
                currency = cur

        ai_total = bill.amount_total  # AI-extracted document total (for the note)

        line_vals = {
            'name': self.merchant_name or self.description or _('Expense'),
            'quantity': 1.0,
            'price_unit': amount,
            'tax_ids': [(6, 0, [])],
            'account_id': account.id,
        }

        bill.write({
            'currency_id': currency.id,
            'invoice_line_ids': [(5, 0, 0), (0, 0, line_vals)],
        })

        # Apply the analytic in a SEPARATE write after the line exists (setting it
        # in the create vals can get wiped by the line's analytic_distribution
        # compute when account_id is set). MERGE it into whatever the line already
        # carries — Odoo's native analytic distribution models may have populated
        # other plans (entity, department, …) and those must be preserved.
        if analytic:
            key = str(analytic.id)
            for line in bill.invoice_line_ids.filtered(lambda l: l.account_id):
                dist = dict(line.analytic_distribution or {})
                if key not in dist:
                    dist[key] = 100
                    line.analytic_distribution = dist

        note = _('Bill amount set from the Revolut transaction: %(amt).2f %(cur)s '
                 '(single gross line, no tax; FX settled at reconciliation).') % {
            'amt': amount, 'cur': currency.name}
        if ai_total and abs(ai_total - amount) > 0.01:
            note += _(' (AI-detected document total was %(ai).2f.)') % {'ai': ai_total}
        bill.message_post(body=note)

    def action_apply_data_source_analytic(self):
        """Backfill: stamp the 'Data Source: Revolut Business API' analytic on the
        expense lines of each linked vendor bill (created or attached) that doesn't
        already carry it. Works on draft and posted bills."""
        updated = skipped = 0
        for rec in self:
            bill = rec.vendor_bill_id
            if not bill:
                skipped += 1
                continue
            analytic = self._ensure_data_source_analytic(rec.company_id)
            key = str(analytic.id)
            changed = False
            for line in bill.invoice_line_ids.filtered(lambda l: l.account_id):
                dist = dict(line.analytic_distribution or {})
                if key not in dist:
                    dist[key] = 100
                    line.analytic_distribution = dist
                    changed = True
            if changed:
                updated += 1
            else:
                skipped += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Apply Data Source analytic'),
                'message': _('%s bill(s) updated, %s skipped (no bill or already tagged).')
                % (updated, skipped),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_reapply_analytic_rules(self):
        """Re-evaluate the analytic rules on each linked bill/invoice and MERGE the
        result onto its expense lines: Odoo's native Analytic Distribution Models
        (by partner/product/account) PLUS the Data Source analytic. Works on posted
        & reconciled documents (analytic_distribution is editable post-posting and
        doesn't affect the GL or reconciliation); existing analytics on other plans
        are preserved (merge, never overwrite). Covers vendor bills and customer
        invoices, created or attached."""
        DistModel = self.env['account.analytic.distribution.model']
        updated = unchanged = skipped = errors = 0
        for rec in self:
            doc = rec.vendor_bill_id or rec.customer_invoice_id
            if not doc:
                skipped += 1
                continue
            try:
                analytic = self._ensure_data_source_analytic(rec.company_id)
                ds_key = str(analytic.id) if analytic else False
                changed = False
                for line in doc.invoice_line_ids.filtered(lambda l: l.account_id):
                    original = dict(line.analytic_distribution or {})
                    dist = dict(original)
                    # 1) native distribution models (entity / department / …)
                    model_dist = DistModel._get_distribution({
                        'product_id': line.product_id.id,
                        'product_categ_id': line.product_id.categ_id.id,
                        'partner_id': line.partner_id.id,
                        'partner_category_id': line.partner_id.category_id.ids,
                        'account_prefix': line.account_id.code,
                        'company_id': line.company_id.id,
                    }) or {}
                    for key, val in model_dist.items():
                        dist.setdefault(str(key), val)   # merge, don't overwrite
                    # 2) Data Source analytic
                    if ds_key:
                        dist.setdefault(ds_key, 100)
                    if dist != original:
                        line.analytic_distribution = dist
                        changed = True
                updated += 1 if changed else 0
                unchanged += 0 if changed else 1
            except Exception as e:  # noqa: BLE001
                errors += 1
                _logger.warning("Reapply analytic rules failed for tx %s: %s", rec.id, e)
        msg = _('%s document(s) updated, %s already current, %s without a bill/invoice, '
                '%s error(s).') % (updated, unchanged, skipped, errors)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reapply analytic rules'),
                'message': msg,
                'type': 'warning' if errors else 'success',
                'sticky': bool(errors),
            },
        }

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

    def _post_lost_to_disallowable(self):
        """Reclassify this tx's suspense bank line to the Disallowable expenses
        account (gross, no tax) + the Data Source analytic — for a 'document lost'
        transaction with no bill. Returns True if a suspense line was booked, False
        if there was nothing in suspense. The bank `amount` is unchanged; once the
        suspense is gone the statement line counts as reconciled."""
        self.ensure_one()
        stmt_line = self.statement_line_id
        if not stmt_line:
            return False
        _liquidity, suspense, _other = stmt_line._seek_for_lines()
        if not suspense:
            return False
        account = self._disallowable_account()
        analytic = self._ensure_data_source_analytic(self.company_id)
        vals = {'account_id': account.id}
        if analytic:
            vals['analytic_distribution'] = {str(analytic.id): 100}
        suspense.write(vals)
        return True

    def _auto_reconcile_bill(self):
        """Reconcile the posted vendor bill with the bank statement line
        using Odoo's bank.rec.widget (the same mechanism as the UI).

        The widget rewrites the statement move to replace the suspense line
        with the bill's payable account, then reconciles both sides.

        Returns (ok, reason): ok=True on success (reason ''), else ok=False with
        a human-readable reason explaining why it could not reconcile.
        """
        self.ensure_one()

        bill = self.vendor_bill_id
        stmt_line = self.statement_line_id

        if not bill or not stmt_line:
            return False, _('missing bill or bank line')

        if bill.state != 'posted':
            return False, _('bill is not posted')

        # The bill's payable line(s).
        payable = bill.line_ids.filtered(
            lambda l: l.account_id.account_type == 'liability_payable'
        )
        if not payable:
            return False, _('the bill has no payable line')

        # Self-heal: if the payable is already reconciled from a previous partial/
        # failed attempt — while the bank line is NOT (the action skips reconciled
        # bank lines before reaching here) — break that stale reconciliation so we
        # can match cleanly against the statement line.
        stale = payable.filtered(
            lambda l: l.reconciled or l.matched_debit_ids or l.matched_credit_ids)
        if stale:
            stale.remove_move_reconcile()

        bill_payable = payable.filtered(lambda l: not l.reconciled)
        if not bill_payable:
            return False, _('no unreconciled payable line on the bill')

        # Make sure the bank line carries the bill's currency as its foreign
        # currency, so a foreign-currency bill reconciles 1:1 and the rate gap
        # posts cleanly to FX gain/loss (repairs lines injected before this was
        # recorded, and covers txs that never captured the original amount).
        self._align_bank_line_to_bill_currency(bill, stmt_line)

        try:
            # Run inside a savepoint so a mid-way failure (e.g. a currency/exchange
            # mismatch) rolls back ALL partial work. Without this, the widget can
            # leave the bill's payable half-reconciled before erroring — and since
            # the caught error doesn't roll the request back, that broken state is
            # committed and every retry then reports "no unreconciled payable line".
            with self.env.cr.savepoint():
                # Use the bank reconciliation widget programmatically
                widget = self.env['bank.rec.widget'].new({
                    'st_line_id': stmt_line.id,
                })
                widget._ensure_loaded_lines()

                # Add the bill's payable line as a match
                widget._action_add_new_amls(bill_payable[:1])

                # Validate — this rewrites the statement move and reconciles
                widget._action_validate()
            return True, ''
        except Exception as e:
            _logger.exception(
                "Auto-reconcile failed for bill %s / statement line %s",
                bill.id, stmt_line.id,
            )
            reason = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
            return False, reason

    def _align_bank_line_to_bill_currency(self, bill, stmt_line):
        """Ensure the bank statement line carries the bill's currency as its
        foreign currency + the bill's exact amount, so a foreign-currency bill
        reconciles 1:1 in that currency and Odoo books the rate gap to FX
        gain/loss. The bank `amount` (actual cash, in the journal currency) is
        NEVER changed. No-op when the bill is in the journal currency or the line
        is already aligned. Only runs on an unreconciled line (caller guarantees)."""
        self.ensure_one()
        journal_ccy = stmt_line.currency_id  # the bank/journal currency
        company_ccy = stmt_line.company_id.currency_id
        bill_ccy = bill.currency_id
        if not bill_ccy or not journal_ccy or bill_ccy == journal_ccy:
            return  # same currency → no foreign leg needed
        if bill_ccy == company_ccy:
            # Tagging the company currency as the bank line's foreign currency makes
            # Odoo treat amount_currency as the company value and corrupts the
            # account's company-currency balance. Reconcile in company currency
            # instead (Odoo handles the cross-currency match + FX natively).
            return
        if not bill.amount_total or not stmt_line.amount:
            return
        target = abs(bill.amount_total) * (-1.0 if stmt_line.amount < 0 else 1.0)
        already = (
            stmt_line.foreign_currency_id == bill_ccy
            and bill_ccy.compare_amounts(stmt_line.amount_currency, target) == 0
        )
        if already:
            return
        stmt_line.write({
            'foreign_currency_id': bill_ccy.id,
            'amount_currency': target,
        })
