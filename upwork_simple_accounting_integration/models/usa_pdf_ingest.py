# -*- coding: utf-8 -*-
"""Shared Upwork multi-page PDF ingestion: split a bulk Upwork document into
single-page PDFs and route each page to the correct usa.transaction.

Both the HTTP controller (/upwork/invoice_upload) and the wizard
(usa.upwork.invoice.upload) delegate to `_ingest_upwork_document` so the
split/classify/route logic lives in exactly one place.

Document layouts (page count + matched-tx type are the discriminators):
  • Type 1 "services delivered" = 3 pages, matched tx is APInvoice/APAdjustment:
    p1 summary (DROP); p2 = our invoice to the client → Customer Invoice;
    p3 = Upwork's service-fee invoice → Vendor Bill (on the linked fee tx).
  • Type 4 "card payment"        = 3 pages, matched tx is ARInvoice/ARPayment:
    p1 summary (DROP); p2 = the Connects/Membership invoice (reference, on the
    Membership-Fee tx); p3 = the "Paid from card" receipt (reference, on the linked
    ARPayment tx). Card-paid memberships park in suspense (GL) — no vendor bill.
  • Type 2 "bill from Upwork"   = 2 pages: p1 summary (DROP);
    p2 = Upwork charge (balance-paid membership/connects) → Vendor Bill.
  • Type 3 "transfer summary"   = 1 page: stored on both the Withdrawal and its
    Withdrawal-Fee tx (reference only).
  • >=4 pages → warn/error (skipped, surfaced to the operator).
"""

import base64
import io
import logging
import re

from odoo import models

_logger = logging.getLogger(__name__)

try:
    from PyPDF2 import PdfReader, PdfWriter
    _HAS_PYPDF = True
except Exception:  # pragma: no cover - environment guard
    PdfReader = PdfWriter = None
    _HAS_PYPDF = False

_TID_RE = re.compile(r'T(\d+)')
_SLUG_RE = re.compile(r'[^A-Za-z0-9._-]+')

# Posting mode → filename role slug (the document each page will become)
_MODE_SLUG = {
    'customer_invoice': 'customer-invoice',
    'customer_refund': 'customer-credit-note',
    'vendor_bill': 'vendor-bill',
    'vendor_refund': 'vendor-credit-note',
    'gl': 'document',
}


class UsaTransactionPdfIngest(models.Model):
    _inherit = 'usa.transaction'

    # ── Public entry point ────────────────────────────────────────────────────

    def _ingest_upwork_document(self, filename, pdf_bytes):
        """Split a bulk Upwork PDF and route its pages to the right transactions.

        Returns a structured result dict (identical shape for controller + wizard):
            {filename, status, doc_type,
             routed: [{role, tx_id, record_id, stored_filename}], message}
        status ∈ {routed, fee_tx_missing, no_id, no_transaction,
                  bad_pagecount, unreadable}
        """
        Tx = self.env['usa.transaction']
        result = {'filename': filename, 'status': None, 'doc_type': None,
                  'routed': [], 'message': ''}

        if not _HAS_PYPDF:
            result.update(status='unreadable',
                          message='PyPDF2 is not available on the server.')
            return result

        # 1. Parse the T<id> token from the filename
        match = _TID_RE.search(filename or '')
        if not match:
            result.update(status='no_id', message='No T<id> token in filename.')
            return result
        tid = match.group(1)

        # 2. Resolve the primary (invoice / charge) transaction — same order as before
        tx = Tx.search([('record_id', '=', tid)], limit=1) \
            or Tx.search([('related_invoice_id', '=', tid)], limit=1)
        if not tx:
            result.update(status='no_transaction',
                          message='No transaction matches T%s.' % tid)
            return result

        # 3. Read the PDF and count pages
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            n_pages = len(reader.pages)
        except Exception as exc:
            _logger.warning('Upwork ingest: cannot read "%s": %s', filename, exc)
            result.update(status='unreadable',
                          message='Could not read the PDF (%s).' % str(exc)[:80])
            return result

        # 4. Classify by page count; a 3-page doc is further split by the matched tx
        #    type (card connects/membership docs match an ARInvoice/ARPayment, whereas
        #    service docs always match an APInvoice/APAdjustment).
        if n_pages == 3:
            if tx.transaction_type in ('ARInvoice', 'ARPayment'):
                return self._route_type4_card(tx, reader, result)
            return self._route_type1_service(tx, reader, result)
        if n_pages == 2:
            return self._route_type2_bill(tx, reader, result)
        if n_pages == 1:
            return self._route_type3_withdrawal(tx, reader, result)
        result.update(
            status='bad_pagecount',
            message='Unexpected %d-page document (expected 1, 2 or 3) — skipped.' % n_pages,
        )
        return result

    # ── Routing ───────────────────────────────────────────────────────────────

    def _route_type1_service(self, primary_tx, reader, result):
        """3-page doc (service OR refund): p2 → the primary tx (customer invoice /
        credit note per its mode); p3 → the linked 'Service Fee' tx (vendor bill /
        credit note per its mode). The document created is driven by injection_mode,
        so this same routing handles services, bonuses and refunds. P1 is dropped."""
        result['doc_type'] = 'type1_service'

        # page 2 (index 1) → the primary transaction
        p2_role = primary_tx.injection_mode
        name2 = primary_tx._build_pdf_name(_MODE_SLUG.get(p2_role, 'document'))
        primary_tx._store_upwork_pdf(self._extract_page(reader, 1), name2)
        result['routed'].append({
            'role': p2_role, 'tx_id': primary_tx.id,
            'record_id': primary_tx.record_id, 'stored_filename': name2,
        })

        # page 3 (index 2) → the linked Service-Fee tx (fee charge OR fee return)
        fee_tx = self.env['usa.transaction'].search([
            ('accounting_subtype', '=', 'Service Fee'),
            ('related_transaction_id', '=', primary_tx.record_id),
        ], limit=1)
        if fee_tx:
            p3_role = fee_tx.injection_mode
            name3 = fee_tx._build_pdf_name(_MODE_SLUG.get(p3_role, 'document'))
            fee_tx._store_upwork_pdf(self._extract_page(reader, 2), name3)
            result['routed'].append({
                'role': p3_role, 'tx_id': fee_tx.id,
                'record_id': fee_tx.record_id, 'stored_filename': name3,
            })
            result.update(
                status='routed',
                message='Page 2 → TX %s (%s), page 3 → TX %s (%s).'
                % (primary_tx.record_id, p2_role, fee_tx.record_id, p3_role))
        else:
            result.update(
                status='fee_tx_missing',
                message='Page 2 → TX %s (%s); no linked Service-Fee transaction '
                'for the fee page.' % (primary_tx.record_id, p2_role))
        return result

    def _route_type4_card(self, tx, reader, result):
        """3-page card-payment doc (Connects/Membership paid by external card):
        p2 = the Connects/Membership invoice → stored on the Membership-Fee ARInvoice tx;
        p3 = the 'Paid from card' receipt → stored on the linked ARPayment tx. Both are
        reference-only — the txs resolve to gl/suspense (see usa.settings
        `_is_card_paid_membership`), so no accounting document is created. P1 is dropped.
        The matched tx may be either side; the pair is resolved via the ARPayment's
        `related_transaction_id` → the Membership-Fee ARInvoice `record_id`."""
        Tx = self.env['usa.transaction']
        result['doc_type'] = 'type4_card'

        if tx.transaction_type == 'ARPayment':
            payment_tx = tx
            invoice_tx = Tx.search([('record_id', '=', tx.related_transaction_id)], limit=1)
        else:  # ARInvoice (Membership Fee)
            invoice_tx = tx
            payment_tx = Tx.search([
                ('transaction_type', '=', 'ARPayment'),
                ('related_transaction_id', '=', tx.record_id),
            ], limit=1)

        # page 2 (index 1) → the Connects/Membership invoice
        if invoice_tx:
            name2 = invoice_tx._build_pdf_name('card-invoice')
            invoice_tx._store_upwork_pdf(self._extract_page(reader, 1), name2)
            result['routed'].append({
                'role': 'card_invoice', 'tx_id': invoice_tx.id,
                'record_id': invoice_tx.record_id, 'stored_filename': name2,
            })

        # page 3 (index 2) → the card-payment receipt
        if payment_tx:
            name3 = payment_tx._build_pdf_name('card-receipt')
            payment_tx._store_upwork_pdf(self._extract_page(reader, 2), name3)
            result['routed'].append({
                'role': 'card_receipt', 'tx_id': payment_tx.id,
                'record_id': payment_tx.record_id, 'stored_filename': name3,
            })

        if invoice_tx and payment_tx:
            result.update(
                status='routed',
                message='Card payment: page 2 → invoice TX %s, page 3 → receipt TX %s '
                '(parked in suspense — no vendor bill).'
                % (invoice_tx.record_id, payment_tx.record_id))
        else:
            present = invoice_tx or payment_tx
            result.update(
                status='payment_tx_missing',
                message='Card payment doc partially routed (TX %s); the paired '
                '%s transaction was not found.'
                % (present.record_id if present else tx.record_id,
                   'card-receipt' if invoice_tx else 'membership-invoice'))
        return result

    def _route_type2_bill(self, tx, reader, result):
        """2-page Upwork charge: p2 → the matched tx (document per its mode)."""
        result['doc_type'] = 'type2_bill'
        role = tx.injection_mode
        name2 = tx._build_pdf_name(_MODE_SLUG.get(role, 'document'))
        tx._store_upwork_pdf(self._extract_page(reader, 1), name2)
        result['routed'].append({
            'role': role, 'tx_id': tx.id,
            'record_id': tx.record_id, 'stored_filename': name2,
        })
        result.update(status='routed',
                      message='Page 2 → TX %s (%s).' % (tx.record_id, role))
        return result

    def _route_type3_withdrawal(self, tx, reader, result):
        """1-page transfer/withdrawal summary → stored on BOTH the Withdrawal tx and
        its linked Withdrawal-Fee tx (reference only; both are gl-mode, so no
        accounting document is created). Other 1-page docs are flagged."""
        Tx = self.env['usa.transaction']
        if tx.accounting_subtype == 'Withdrawal':
            withdrawal = tx
            fee = Tx.search([
                ('accounting_subtype', '=', 'Withdrawal Fee'),
                ('related_transaction_id', '=', tx.record_id),
            ], limit=1)
        elif tx.accounting_subtype == 'Withdrawal Fee':
            fee = tx
            withdrawal = Tx.search([('record_id', '=', tx.related_transaction_id)], limit=1)
        else:
            result.update(
                status='bad_pagecount',
                message='1-page document for a non-withdrawal transaction (T%s) — skipped.'
                % tx.record_id)
            return result

        result['doc_type'] = 'type3_withdrawal'
        page = self._extract_page(reader, 0)
        targets = withdrawal | fee   # recordset union skips empties
        for target in targets:
            name = target._build_pdf_name('withdrawal-summary')
            target._store_upwork_pdf(page, name)
            result['routed'].append({
                'role': 'withdrawal_summary', 'tx_id': target.id,
                'record_id': target.record_id, 'stored_filename': name,
            })
        result.update(
            status='routed',
            message='Transfer summary → %d transaction(s) (withdrawal + fee).' % len(targets))
        return result

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_page(reader, index):
        """Return single-page PDF bytes for page `index` (0-based)."""
        writer = PdfWriter()
        writer.add_page(reader.pages[index])
        buf = io.BytesIO()
        writer.write(buf)
        return buf.getvalue()

    def _store_upwork_pdf(self, pdf_bytes, filename):
        """Store a single-page PDF onto this transaction's upwork_invoice_pdf."""
        self.ensure_one()
        self.write({
            'upwork_invoice_pdf': base64.b64encode(pdf_bytes).decode(),
            'upwork_invoice_filename': filename,
        })

    def _build_pdf_name(self, role):
        """Build an identifiable filename: upwork_<record_id>_<role>_<client>.pdf."""
        self.ensure_one()
        client = _SLUG_RE.sub('-', (self.assignment_company_name or '').strip())[:40].strip('-')
        return 'upwork_%s_%s_%s.pdf' % (self.record_id or 'na', role, client or 'na')
