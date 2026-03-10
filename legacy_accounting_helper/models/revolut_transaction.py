import base64
import datetime
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TRANSACTION_TYPE_SELECTION = [
    ('atm', 'ATM'),
    ('card_payment', 'Card Payment'),
    ('card_refund', 'Card Refund'),
    ('card_chargeback', 'Card Chargeback'),
    ('card_credit', 'Card Credit'),
    ('exchange', 'Exchange'),
    ('transfer', 'Transfer'),
    ('loan', 'Loan'),
    ('fee', 'Fee'),
    ('refund', 'Refund'),
    ('topup', 'Top-up'),
    ('topup_return', 'Top-up Return'),
    ('tax', 'Tax'),
    ('tax_refund', 'Tax Refund'),
    ('merchant_payment', 'Merchant Payment'),
    ('charge', 'Charge'),
]

TRANSACTION_STATE_SELECTION = [
    ('created', 'Created'),
    ('pending', 'Pending'),
    ('completed', 'Completed'),
    ('declined', 'Declined'),
    ('failed', 'Failed'),
    ('reverted', 'Reverted'),
]


class RevolutTransaction(models.Model):
    _name = 'revolut.transaction'
    _description = 'Revolut Business Transaction'
    _order = 'created_at desc'
    _rec_name = 'revolut_id'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company, index=True,
    )
    revolut_id = fields.Char(string='Revolut ID', required=True, index=True, readonly=True)

    transaction_type = fields.Selection(
        TRANSACTION_TYPE_SELECTION, string='Type', readonly=True, index=True,
    )
    state = fields.Selection(
        TRANSACTION_STATE_SELECTION, string='State', readonly=True, index=True,
    )
    reason_code = fields.Char(string='Reason Code', readonly=True)

    created_at = fields.Datetime(string='Created At', readonly=True, index=True)
    updated_at = fields.Datetime(string='Updated At', readonly=True)
    completed_at = fields.Datetime(string='Completed At', readonly=True)
    scheduled_for = fields.Datetime(string='Scheduled For', readonly=True)

    reference = fields.Char(string='Reference', readonly=True)
    related_transaction_id = fields.Char(string='Related Transaction ID', readonly=True)

    # Merchant
    merchant_name = fields.Char(string='Merchant', readonly=True, index=True)
    merchant_city = fields.Char(string='Merchant City', readonly=True)
    merchant_category_code = fields.Char(string='MCC', readonly=True)
    merchant_country = fields.Char(string='Merchant Country', readonly=True, index=True)

    # Primary leg values (denormalised for quick list view)
    amount = fields.Float(string='Amount', digits=(16, 4), readonly=True)
    currency = fields.Char(string='Currency', size=3, readonly=True, index=True)
    description = fields.Char(string='Description', readonly=True)

    # Account
    account_revolut_id = fields.Char(string='Account ID', readonly=True, index=True)
    account_name = fields.Char(string='Account', readonly=True, index=True)

    leg_ids = fields.One2many(
        'revolut.transaction.leg', 'transaction_id', string='Legs', readonly=True,
    )
    raw_json = fields.Text(string='Raw JSON', readonly=True)

    # ── Supporting documents ──────────────────────────────────────────────────

    invoice_attachment_ids = fields.Many2many(
        'ir.attachment',
        'revolut_transaction_attachment_rel',
        'transaction_id',
        'attachment_id',
        string='Attached Invoice/Bill',
    )
    invoice_attachment_count = fields.Integer(
        string='Receipts',
        compute='_compute_invoice_attachment_count',
    )

    # ── Gmail Lookup ──────────────────────────────────────────────────────────

    # Hidden backing fields — store any value the user has explicitly set.
    # When NULL the computed fields below fall back to description / created_at.
    gmail_keywords_custom = fields.Char(store=True, copy=False)
    gmail_date_custom = fields.Date(store=True, copy=False)

    gmail_search_keywords = fields.Char(
        string='Search Keywords',
        compute='_compute_gmail_search_keywords',
        inverse='_inverse_gmail_search_keywords',
    )
    gmail_search_date = fields.Date(
        string='Search Date',
        compute='_compute_gmail_search_date',
        inverse='_inverse_gmail_search_date',
    )
    gmail_search_range = fields.Integer(string='Date Range (days)', default=3)
    gmail_search_with_attachment = fields.Boolean(
        string='With Attachment Only', default=True,
    )
    gmail_search_performed = fields.Boolean(default=False)
    gmail_search_results_count = fields.Integer(default=0)
    gmail_search_results_html = fields.Html(
        string='Gmail Results', sanitize=False,
    )
    gmail_found_attachment_ids = fields.One2many(
        'revolut.gmail.attachment', 'transaction_id', string='Found Gmail Attachments',
    )

    # ── Revolut staged receipts ───────────────────────────────────────────────

    revolut_fetched_receipt_ids = fields.One2many(
        'revolut.fetched.receipt', 'transaction_id', string='Fetched Receipts',
    )
    revolut_fetch_performed = fields.Boolean(default=False, copy=False)
    revolut_fetched_count = fields.Integer(
        compute='_compute_revolut_fetched_count',
    )

    google_user_connected = fields.Boolean(
        string='Google Connected',
        compute='_compute_google_user_connected',
        store=False,
    )

    def _compute_google_user_connected(self):
        for rec in self:
            creds = self.env.user.sudo().google_account_id
            rec.google_user_connected = bool(creds and creds._is_authorized())

    def _compute_revolut_fetched_count(self):
        for rec in self:
            rec.revolut_fetched_count = len(rec.revolut_fetched_receipt_ids)

    @api.depends('gmail_keywords_custom', 'description')
    def _compute_gmail_search_keywords(self):
        for rec in self:
            rec.gmail_search_keywords = rec.gmail_keywords_custom or rec.description or False

    def _inverse_gmail_search_keywords(self):
        for rec in self:
            rec.gmail_keywords_custom = rec.gmail_search_keywords or False

    @api.depends('gmail_date_custom', 'created_at')
    def _compute_gmail_search_date(self):
        for rec in self:
            if rec.gmail_date_custom:
                rec.gmail_search_date = rec.gmail_date_custom
            elif rec.created_at:
                rec.gmail_search_date = rec.created_at.date()
            else:
                rec.gmail_search_date = False

    def _inverse_gmail_search_date(self):
        for rec in self:
            rec.gmail_date_custom = rec.gmail_search_date or False

    # ── Receipt preview ───────────────────────────────────────────────────────

    receipt_preview = fields.Binary(
        string='Receipt Preview', compute='_compute_receipt_preview', store=False,
    )
    receipt_preview_filename = fields.Char(
        compute='_compute_receipt_preview', store=False,
    )
    receipt_is_pdf = fields.Boolean(
        compute='_compute_receipt_preview', store=False,
    )
    receipt_first_attachment_id = fields.Many2one(
        'ir.attachment', compute='_compute_receipt_preview', store=False,
    )
    receipt_list_html = fields.Html(
        string='Receipt', compute='_compute_receipt_list_html', store=False, sanitize=False,
    )

    def _compute_invoice_attachment_count(self):
        for rec in self:
            rec.invoice_attachment_count = len(rec.invoice_attachment_ids)

    @api.depends('invoice_attachment_ids', 'invoice_attachment_ids.mimetype',
                 'invoice_attachment_ids.datas')
    def _compute_receipt_preview(self):
        for rec in self:
            attachment = rec.invoice_attachment_ids[:1] if rec.invoice_attachment_ids else False
            if attachment:
                mimetype = attachment.mimetype or ''
                rec.receipt_first_attachment_id = attachment
                rec.receipt_preview_filename = attachment.name
                if mimetype.startswith('image/'):
                    rec.receipt_preview = attachment.datas
                    rec.receipt_is_pdf = False
                elif mimetype == 'application/pdf':
                    rec.receipt_preview = False
                    rec.receipt_is_pdf = True
                else:
                    rec.receipt_preview = False
                    rec.receipt_is_pdf = False
            else:
                rec.receipt_first_attachment_id = False
                rec.receipt_preview = False
                rec.receipt_preview_filename = False
                rec.receipt_is_pdf = False

    @api.depends('invoice_attachment_ids', 'invoice_attachment_ids.mimetype')
    def _compute_receipt_list_html(self):
        for rec in self:
            attachment = rec.invoice_attachment_ids[:1] if rec.invoice_attachment_ids else False
            if not attachment:
                rec.receipt_list_html = ''
                continue
            mimetype = attachment.mimetype or ''
            if mimetype.startswith('image/'):
                rec.receipt_list_html = (
                    f'<img src="/web/image/ir.attachment/{attachment.id}/datas" '
                    f'style="max-height:38px;max-width:52px;object-fit:contain;'
                    f'border-radius:3px;border:1px solid #dee2e6;"/>'
                )
            elif mimetype == 'application/pdf':
                rec.receipt_list_html = (
                    '<span style="display:inline-block;background:#dc3545;color:#fff;'
                    'border-radius:3px;padding:2px 6px;font-size:10px;font-weight:700;'
                    'letter-spacing:.5px;">PDF</span>'
                )
            else:
                ext = (attachment.name or '').rsplit('.', 1)[-1].upper()[:5] or 'FILE'
                rec.receipt_list_html = (
                    f'<span style="display:inline-block;background:#6c757d;color:#fff;'
                    f'border-radius:3px;padding:2px 6px;font-size:10px;font-weight:700;'
                    f'letter-spacing:.5px;">{ext}</span>'
                )

    def action_open_receipt_pdf(self):
        """Open the first PDF attachment in a new browser tab."""
        attachment = self.receipt_first_attachment_id
        if not attachment:
            raise UserError('No receipt attachment found.')
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=false',
            'target': 'new',
        }

    _sql_constraints = [
        (
            'revolut_id_company_uniq',
            'unique(revolut_id, company_id)',
            'A transaction with this Revolut ID already exists for this company.',
        ),
    ]

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_dt(val):
        if not val:
            return False
        try:
            return datetime.datetime.fromisoformat(
                val.replace('Z', '+00:00')
            ).replace(tzinfo=None)
        except Exception:
            return False

    def _revolut_get(self, path, access_token, params=None):
        url = f'https://b2b.revolut.com/api/1.0{path}'
        if params:
            url = f'{url}?{urllib.parse.urlencode(params)}'
        for attempt in range(3):
            req = urllib.request.Request(url)
            req.add_header('Accept', 'application/json')
            req.add_header('Authorization', f'Bearer {access_token}')
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 2:
                    time.sleep(1)
                    continue
                if e.code == 401 and attempt == 0:
                    _logger.info("Revolut API 401 on %s — attempting token refresh.", path)
                    config = self.env['legacy.accounting.config'].sudo().search(
                        [('company_id', '=', self.env.company.id)], limit=1
                    )
                    if config:
                        new_token = config._do_refresh_token()
                        if new_token:
                            access_token = new_token
                            continue
                raise UserError(f'Revolut API error {e.code}: {e.read().decode()}')
            except Exception as e:
                raise UserError(f'Request failed: {e}')

    def _upsert_transaction(self, tx_data, account_id, account_name):
        tx_id = tx_data.get('id')
        if not tx_id:
            return None

        legs = tx_data.get('legs') or []
        primary_leg = next(
            (l for l in legs if l.get('account_id') == account_id), None
        ) or (legs[0] if legs else {})
        merchant = tx_data.get('merchant') or {}

        vals = {
            'company_id': self.env.company.id,
            'revolut_id': tx_id,
            'transaction_type': tx_data.get('type'),
            'state': tx_data.get('state'),
            'reason_code': tx_data.get('reason_code') or False,
            'created_at': self._parse_dt(tx_data.get('created_at')),
            'updated_at': self._parse_dt(tx_data.get('updated_at')),
            'completed_at': self._parse_dt(tx_data.get('completed_at')),
            'scheduled_for': self._parse_dt(tx_data.get('scheduled_for')),
            'reference': tx_data.get('reference') or False,
            'related_transaction_id': tx_data.get('related_transaction_id') or False,
            'merchant_name': merchant.get('name') or False,
            'merchant_city': merchant.get('city') or False,
            'merchant_category_code': merchant.get('category_code') or False,
            'merchant_country': merchant.get('country') or False,
            'amount': primary_leg.get('amount') or 0.0,
            'currency': primary_leg.get('currency') or False,
            'description': primary_leg.get('description') or False,
            'account_revolut_id': account_id,
            'account_name': account_name,
            'raw_json': json.dumps(tx_data, default=str),
        }

        existing = self.search([
            ('revolut_id', '=', tx_id),
            ('company_id', '=', self.env.company.id),
        ], limit=1)

        if existing:
            existing.write(vals)
            existing.leg_ids.unlink()
            record = existing
        else:
            record = self.create(vals)

        Leg = self.env['revolut.transaction.leg']
        for leg in legs:
            cp = leg.get('counterparty') or {}
            Leg.create({
                'transaction_id': record.id,
                'leg_id': leg.get('leg_id') or False,
                'amount': leg.get('amount') or 0.0,
                'fee': leg.get('fee') or 0.0,
                'currency': leg.get('currency') or False,
                'bill_amount': leg.get('bill_amount') or 0.0,
                'bill_currency': leg.get('bill_currency') or False,
                'account_id': leg.get('account_id') or False,
                'counterparty_id': cp.get('id') or False,
                'counterparty_account_id': cp.get('account_id') or False,
                'counterparty_account_type': cp.get('account_type') or False,
                'description': leg.get('description') or False,
                'balance': leg.get('balance') or 0.0,
            })

        return bool(existing)

    # ── Supporting document actions ───────────────────────────────────────────

    def _revolut_download(self, url, access_token):
        """Download raw bytes from a URL with Bearer auth. Returns (content, content_type)."""
        for attempt in range(3):
            req = urllib.request.Request(url)
            req.add_header('Accept', 'application/json')
            req.add_header('Authorization', f'Bearer {access_token}')
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return resp.read(), resp.headers.get('Content-Type', 'application/octet-stream')
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 2:
                    time.sleep(1)
                    continue
                if e.code == 401 and attempt == 0:
                    _logger.info("Revolut API 401 on download — attempting token refresh.")
                    config = self.env['legacy.accounting.config'].sudo().search(
                        [('company_id', '=', self.env.company.id)], limit=1
                    )
                    if config:
                        new_token = config._do_refresh_token()
                        if new_token:
                            access_token = new_token
                            continue
                raise

    @staticmethod
    def _ext_from_content_type(content_type):
        ct = content_type.lower()
        if 'pdf' in ct:
            return 'pdf'
        if 'png' in ct:
            return 'png'
        if 'jpeg' in ct or 'jpg' in ct:
            return 'jpg'
        if 'gif' in ct:
            return 'gif'
        if 'webp' in ct:
            return 'webp'
        return 'bin'

    def _fetch_receipts_for_record(self, record, token):
        """
        1. GET /api/1.0/expenses?transaction_id=<revolut_id>
        2. For each receipt_id in expense.receipt_ids:
               GET /api/1.0/expenses/{id}/receipts/{rid}/content
        Returns list of created ir.attachment records.
        Raises UserError with a clear message if anything goes wrong.
        """
        # Remove any previously fetched attachments so re-fetch replaces instead of accumulating
        if record.invoice_attachment_ids:
            old_attachments = record.invoice_attachment_ids
            # Nullify staged receipt references first to avoid FK violation
            self.env['revolut.fetched.receipt'].sudo().search(
                [('attachment_id', 'in', old_attachments.ids)]
            ).write({'attachment_id': False})
            record.write({'invoice_attachment_ids': [(5, 0, 0)]})
            old_attachments.sudo().unlink()

        # Step 1 — fetch expenses in a ±3 day window around the transaction date,
        # then match by transaction_id client-side (Revolut ignores the query param)
        if not record.created_at:
            raise UserError(
                f'Transaction {record.revolut_id} has no date — cannot search expenses.'
            )
        from_date = (record.created_at - datetime.timedelta(days=3)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        to_date = (record.created_at + datetime.timedelta(days=3)).strftime('%Y-%m-%dT%H:%M:%S.000Z')

        batch = self._revolut_get('/expenses', token, params={
            'from': from_date,
            'to': to_date,
            'count': 1000,
        })
        if not isinstance(batch, list):
            raise UserError(
                f'Unexpected response from /expenses: {type(batch).__name__}'
            )
        expense = next(
            (exp for exp in batch if exp.get('transaction_id') == record.revolut_id),
            None,
        )

        if not expense:
            raise UserError(
                f'No expense found for transaction {record.revolut_id}.\n'
                f'Only card payments with a submitted expense in Revolut have receipts.'
            )

        receipt_ids = expense.get('receipt_ids') or []
        if not receipt_ids:
            raise UserError(
                f'Expense {expense.get("id")} found but has no receipt_ids. '
                f'Upload a receipt in Revolut first.'
            )

        # Step 3 — download each receipt and create ir.attachment
        expense_id = expense.get('id')
        new_attachments = self.env['ir.attachment']

        for receipt_id in receipt_ids:
            url = (
                f'https://b2b.revolut.com/api/1.0'
                f'/expenses/{expense_id}/receipts/{receipt_id}/content'
            )
            try:
                content, content_type = self._revolut_download(url, token)
            except urllib.error.HTTPError as e:
                raise UserError(
                    f'Failed to download receipt {receipt_id}: '
                    f'HTTP {e.code} — {e.read().decode()}'
                )
            except Exception as e:
                raise UserError(f'Failed to download receipt {receipt_id}: {e}')

            ext = self._ext_from_content_type(content_type)
            attachment = self.env['ir.attachment'].sudo().create({
                'name': f'{record.revolut_id}_receipt_{receipt_id}.{ext}',
                'type': 'binary',
                'datas': base64.b64encode(content),
                'mimetype': content_type.split(';')[0].strip(),
                'res_model': 'revolut.transaction',
                'res_id': record.id,
            })
            new_attachments |= attachment

        return new_attachments

    def action_fetch_revolut_attachments(self):
        """
        Single record: raise UserError immediately so the user sees the exact problem.
        Batch (list view action): collect per-record results and show a summary.
        """
        config = self.env['legacy.accounting.config'].sudo().search(
            [('company_id', '=', self.env.company.id)], limit=1
        )
        if not config or not config.access_token:
            raise UserError(
                'No access token found. '
                'Complete Step 4 in Revolut Business API Integration first.'
            )

        token = config.access_token.strip()

        # ── Single record: propagate errors so user sees them ─────────────────
        if len(self) == 1:
            record = self
            new_attachments = self._fetch_receipts_for_record(record, token)
            record.invoice_attachment_ids = [(4, a.id) for a in new_attachments]
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Receipts Fetched',
                    'message': f'{len(new_attachments)} receipt(s) attached successfully.',
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'},
                },
            }

        # ── Batch: per-record bus notifications + final summary ───────────────
        fetched = 0
        skipped = 0
        partner = self.env.user.partner_id

        for record in self:
            try:
                new_attachments = self._fetch_receipts_for_record(record, token)
                record.invoice_attachment_ids = [(4, a.id) for a in new_attachments]
                fetched += 1
                self.env['bus.bus']._sendone(partner, 'simple_notification', {
                    'type': 'success',
                    'title': 'Receipt Found',
                    'message': f'{record.revolut_id}: {len(new_attachments)} receipt(s) attached.',
                    'sticky': False,
                })
            except UserError as e:
                skipped += 1
                self.env['bus.bus']._sendone(partner, 'simple_notification', {
                    'type': 'warning',
                    'title': 'Receipt Not Found',
                    'message': f'{record.revolut_id}: {e.args[0][:120]}',
                    'sticky': False,
                })

        total = len(self)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Revolut Receipts — Done',
                'message': f'Batch complete: {fetched}/{total} receipts fetched, {skipped} skipped.',
                'type': 'success' if fetched else 'warning',
                'sticky': True,
            },
        }

    def action_remove_attachments(self):
        """Batch-remove all invoice attachments from the selected transactions."""
        removed = 0
        for record in self:
            if record.invoice_attachment_ids:
                old = record.invoice_attachment_ids
                record.write({'invoice_attachment_ids': [(5, 0, 0)]})
                old.unlink()
                removed += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Attachments Removed',
                'message': f'Removed attachments from {removed} transaction(s).',
                'type': 'success' if removed else 'warning',
                'sticky': False,
            },
        }

    # ── Revolut staged fetch (form-view flow) ────────────────────────────────

    def _fetch_and_stage_revolut_receipts(self, token):
        """
        Download receipts from Revolut API and create revolut.fetched.receipt
        staging records. Does NOT attach anything to invoice_attachment_ids.
        Marks revolut_fetch_performed=True regardless of outcome.
        Raises UserError only for hard failures (bad API response); silently
        skips missing expenses/receipts so auto-fetch never crashes.
        """
        self.revolut_fetch_performed = True

        if not self.created_at:
            return

        from_date = (self.created_at - datetime.timedelta(days=3)).strftime(
            '%Y-%m-%dT%H:%M:%S.000Z'
        )
        to_date = (self.created_at + datetime.timedelta(days=3)).strftime(
            '%Y-%m-%dT%H:%M:%S.000Z'
        )

        batch = self._revolut_get('/expenses', token, params={
            'from': from_date, 'to': to_date, 'count': 1000,
        })
        if not isinstance(batch, list):
            return  # Unexpected response — silently stop

        expense = next(
            (exp for exp in batch if exp.get('transaction_id') == self.revolut_id),
            None,
        )
        if not expense:
            return  # No expense for this transaction

        receipt_ids = expense.get('receipt_ids') or []
        if not receipt_ids:
            return  # Expense exists but no receipts uploaded in Revolut

        expense_id = expense.get('id')
        FetchedReceipt = self.env['revolut.fetched.receipt']
        IrAttachment = self.env['ir.attachment']

        for receipt_id in receipt_ids:
            url = (
                f'https://b2b.revolut.com/api/1.0'
                f'/expenses/{expense_id}/receipts/{receipt_id}/content'
            )
            try:
                content, content_type = self._revolut_download(url, token)
            except Exception as e:
                _logger.warning(
                    "Failed to download Revolut receipt %s: %s", receipt_id, e
                )
                continue

            ext = self._ext_from_content_type(content_type)
            mime = content_type.split(';')[0].strip()
            filename = f'{self.revolut_id}_receipt_{receipt_id}.{ext}'

            attachment = IrAttachment.sudo().create({
                'name': filename,
                'type': 'binary',
                'datas': base64.b64encode(content),
                'mimetype': mime,
            })
            receipt = FetchedReceipt.create({
                'transaction_id': self.id,
                'attachment_id': attachment.id,
                'revolut_expense_id': expense_id,
                'revolut_receipt_id': receipt_id,
                'name': filename,
                'mime_type': mime,
            })
            # Link attachment to its staged receipt so Odoo's ACL lets any user
            # with access to revolut.fetched.receipt also read the file.
            attachment.sudo().write({
                'res_model': 'revolut.fetched.receipt',
                'res_id': receipt.id,
            })

    def action_fetch_revolut_staged(self):
        """
        Form-view button: fetch receipts from Revolut and stage them for review.
        The user then explicitly clicks 'Attach' for each file they want to keep.
        Re-clicking clears previous staged results and re-fetches fresh.
        """
        self.ensure_one()
        config = self.env['legacy.accounting.config'].sudo().search(
            [('company_id', '=', self.env.company.id)], limit=1
        )
        if not config or not config.access_token:
            raise UserError(
                'No access token found. '
                'Complete Step 4 in Revolut Business API Integration first.'
            )

        # Clear previously staged (non-attached) receipts before re-fetching
        old_staged = self.revolut_fetched_receipt_ids
        if old_staged:
            old_staged.unlink()

        self.write({'revolut_fetch_performed': False})

        self._fetch_and_stage_revolut_receipts(config.access_token.strip())
        return False

    def action_auto_fetch(self):
        """
        Called automatically by the JS patch when the form view is opened.
        Runs Revolut fetch and Gmail search if not already performed for this record.
        All errors are swallowed — auto-fetch must never break the form.
        """
        self.ensure_one()

        # Auto-fetch Revolut receipts if not yet done
        if not self.revolut_fetch_performed:
            config = self.env['legacy.accounting.config'].sudo().search(
                [('company_id', '=', self.env.company.id)], limit=1
            )
            if config and config.access_token:
                try:
                    self._fetch_and_stage_revolut_receipts(config.access_token.strip())
                except Exception as e:
                    _logger.info(
                        "Auto-fetch Revolut receipts skipped for %s: %s",
                        self.revolut_id, e,
                    )
                    self.revolut_fetch_performed = True  # avoid repeated attempts

        # Auto-search Gmail if user is connected and search not yet performed
        if not self.gmail_search_performed:
            creds = self.env.user.sudo().google_account_id
            if creds and creds._is_authorized():
                try:
                    self.action_gmail_search()
                except Exception as e:
                    _logger.info(
                        "Auto-search Gmail skipped for %s: %s",
                        self.revolut_id, e,
                    )

        return False

    def action_fetch_gmail_attachments(self):
        """Legacy placeholder — kept for backwards compatibility."""
        return self.action_gmail_search()

    # ── Gmail Lookup actions ───────────────────────────────────────────────────

    def _build_gmail_service(self):
        """Build and return an authenticated Gmail API service for the current user."""
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError:
            raise UserError(
                "Google API client libraries are not installed.\n"
                "Please install them: pip install google-api-python-client google-auth"
            )

        user = self.env.user
        creds_record = user.sudo().google_account_id
        if not creds_record or not creds_record._is_authorized():
            raise UserError(
                "Google account is not connected.\n"
                "Please connect via Revolut Business API Integration → Google / Gmail Setup."
            )

        get_param = self.env['ir.config_parameter'].sudo().get_param
        client_id = get_param('google_gmail_client_id')
        client_secret = get_param('google_gmail_client_secret')
        access_token = creds_record._get_valid_access_token()

        creds = Credentials(
            token=access_token,
            refresh_token=creds_record.sudo().refresh_token,
            token_uri='https://oauth2.googleapis.com/token',
            client_id=client_id,
            client_secret=client_secret,
            scopes=['https://www.googleapis.com/auth/gmail.readonly'],
        )
        return build('gmail', 'v1', credentials=creds)

    @staticmethod
    def _gmail_build_query(keywords, search_date, search_range, with_attachment):
        """Build a Gmail search query string."""
        import datetime as _dt
        parts = []
        if keywords:
            parts.append(keywords.strip())
        if with_attachment:
            parts.append('has:attachment')
        if search_date:
            if isinstance(search_date, str):
                search_date = _dt.date.fromisoformat(search_date)
            delta = _dt.timedelta(days=max(0, search_range or 3))
            start = search_date - delta
            end = search_date + delta
            parts.append(f'after:{start.strftime("%Y/%m/%d")}')
            parts.append(f'before:{end.strftime("%Y/%m/%d")}')
        return ' '.join(parts)

    @staticmethod
    def _gmail_extract_body(payload):
        """Recursively extract plain-text body from Gmail message payload."""
        import base64 as _b64
        text_body = ''

        def decode_data(data):
            if data:
                padded = data + '=' * (-len(data) % 4)
                return _b64.urlsafe_b64decode(padded).decode('utf-8', errors='replace')
            return ''

        def process_part(part):
            nonlocal text_body
            mime = part.get('mimeType', '')
            body_data = part.get('body', {}).get('data', '')
            if mime == 'text/plain' and not text_body:
                text_body = decode_data(body_data)
            elif mime.startswith('multipart/'):
                for subpart in part.get('parts', []):
                    process_part(subpart)

        process_part(payload)
        return text_body

    @staticmethod
    def _gmail_format_size(size_bytes):
        if not size_bytes:
            return ''
        if size_bytes < 1024:
            return f'{size_bytes} B'
        if size_bytes < 1024 * 1024:
            return f'{size_bytes // 1024} KB'
        return f'{size_bytes / (1024 * 1024):.1f} MB'

    def _gmail_render_cards_html(self, messages_data):
        """Render email cards HTML from list of parsed message dicts."""
        import html as _html_mod

        _AVATAR_COLORS = [
            '#1a73e8', '#34a853', '#ea4335', '#9c27b0',
            '#00796b', '#f4511e', '#039be5', '#8d6e63',
        ]

        def sender_initial(sender_str):
            import re
            m = re.match(r'^"?([^"<]+)"?\s*<', sender_str or '')
            name = m.group(1).strip() if m else (sender_str or '').split('@')[0]
            return (name[0] if name else '?').upper()

        e = _html_mod.escape
        cards = []
        for idx, msg in enumerate(messages_data):
            avatar_color = _AVATAR_COLORS[idx % len(_AVATAR_COLORS)]
            avatar_letter = e(sender_initial(msg.get('from', '')))
            sender_esc = e(msg.get('from', '—'))
            subject_esc = e(msg.get('subject', '(No Subject)'))
            date_esc = e(msg.get('date', ''))
            snippet_esc = e(msg.get('snippet', ''))

            att_count = msg.get('attachment_count', 0)
            att_info = (
                f'<div style="padding:8px 16px;background:#f0f4ff;border-top:1px solid #c5cae9;">'
                f'<span style="font-size:12px;color:#3949ab;font-weight:700;">&#128206;&nbsp;'
                f'{att_count} attachment(s) found — see table below</span>'
                f'</div>'
            ) if att_count else ''

            card = (
                f'<div style="border:1px solid #dadce0;border-radius:10px;'
                f'margin-bottom:12px;overflow:hidden;background:#fff;'
                f'box-shadow:0 1px 3px rgba(60,64,67,.12);">'
                f'<div style="padding:10px 16px;background:#f8f9fa;'
                f'border-bottom:1px solid #e8eaed;display:flex;align-items:center;gap:12px;">'
                f'<div style="width:34px;height:34px;border-radius:50%;'
                f'background:{avatar_color};color:#fff;display:inline-flex;'
                f'align-items:center;justify-content:center;font-size:14px;'
                f'font-weight:700;flex-shrink:0;">{avatar_letter}</div>'
                f'<div style="flex:1;min-width:0;">'
                f'<div style="font-size:13px;color:#202124;white-space:nowrap;'
                f'overflow:hidden;text-overflow:ellipsis;">'
                f'<span style="font-weight:600;color:#5f6368;margin-right:4px;">From:</span>'
                f'{sender_esc}</div>'
                f'<div style="font-size:13px;margin-top:2px;white-space:nowrap;'
                f'overflow:hidden;text-overflow:ellipsis;">'
                f'<span style="font-weight:600;color:#5f6368;margin-right:4px;">Subject:</span>'
                f'<strong>{subject_esc}</strong></div>'
                f'</div>'
                f'<div style="font-size:12px;color:#5f6368;white-space:nowrap;'
                f'flex-shrink:0;align-self:flex-start;padding-top:2px;">{date_esc}</div>'
                f'</div>'
                f'<div style="padding:10px 16px;font-size:13px;color:#5f6368;">'
                f'{snippet_esc}</div>'
                f'{att_info}'
                f'</div>'
            )
            cards.append(card)

        if not cards:
            return ''
        return (
            '<div style="padding:0;margin:0;">'
            + '\n'.join(cards)
            + '</div>'
        )

    def action_gmail_search(self):
        """Search Gmail and populate gmail_found_attachment_ids."""
        self.ensure_one()
        service = self._build_gmail_service()

        query = self._gmail_build_query(
            self.gmail_search_keywords,
            self.gmail_search_date,
            self.gmail_search_range,
            self.gmail_search_with_attachment,
        )

        # Clear previous results
        self.gmail_found_attachment_ids.unlink()
        self.write({
            'gmail_search_results_html': False,
            'gmail_search_results_count': 0,
            'gmail_search_performed': False,
        })

        try:
            response = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=20,
            ).execute()
        except Exception as exc:
            err = str(exc)
            if '403' in err or 'PERMISSION_DENIED' in err or 'insufficientPermissions' in err:
                raise UserError(
                    "Gmail access not authorized. Please reconnect your Google account "
                    "via Google / Gmail Setup to grant Gmail (gmail.readonly) access."
                )
            raise UserError(f"Gmail API search failed: {exc}")

        messages_meta = response.get('messages', [])
        self.gmail_search_performed = True

        if not messages_meta:
            self.write({
                'gmail_search_results_html': (
                    '<p class="text-muted">No emails found matching your search.</p>'
                ),
                'gmail_search_results_count': 0,
            })
            return False

        GmailAtt = self.env['revolut.gmail.attachment']
        total_attachments = 0
        cards_data = []

        for msg_meta in messages_meta:
            msg_id = msg_meta['id']
            try:
                msg = service.users().messages().get(
                    userId='me', id=msg_id, format='full',
                ).execute()
            except Exception as exc:
                _logger.warning(
                    "Failed to fetch Gmail message %s: %s", msg_id, exc
                )
                continue

            payload = msg.get('payload', {})
            headers = {
                h['name'].lower(): h['value']
                for h in payload.get('headers', [])
            }
            subject = headers.get('subject', '(No Subject)')
            from_str = headers.get('from', '')
            date_str = headers.get('date', '')
            snippet = msg.get('snippet', '')

            att_count_msg = 0

            def find_attachments(part):
                nonlocal att_count_msg
                filename = part.get('filename')
                att_id = part.get('body', {}).get('attachmentId')
                if filename and att_id:
                    att_count_msg += 1
                    size = part.get('body', {}).get('size', 0)
                    GmailAtt.create({
                        'transaction_id': self.id,
                        'gmail_message_id': msg_id,
                        'gmail_attachment_id': att_id,
                        'name': filename,
                        'mime_type': part.get('mimeType', 'application/octet-stream'),
                        'size_display': self._gmail_format_size(size),
                        'email_subject': subject,
                        'email_from': from_str,
                        'email_date': date_str,
                    })
                for subpart in part.get('parts', []):
                    find_attachments(subpart)

            find_attachments(payload)
            total_attachments += att_count_msg

            cards_data.append({
                'from': from_str,
                'subject': subject,
                'date': date_str,
                'snippet': snippet,
                'attachment_count': att_count_msg,
            })

        html = self._gmail_render_cards_html(cards_data)
        self.write({
            'gmail_search_results_html': html,
            'gmail_search_results_count': total_attachments,
        })
        # Return False → Odoo form controller reloads the current record
        return False

    def action_gmail_clear(self):
        """Clear Gmail search results and reset search inputs to defaults."""
        self.ensure_one()
        self.gmail_found_attachment_ids.unlink()
        self.write({
            'gmail_search_results_html': False,
            'gmail_search_results_count': 0,
            'gmail_search_performed': False,
            # Reset custom overrides so keywords/date fall back to description/created_at
            'gmail_keywords_custom': False,
            'gmail_date_custom': False,
            'gmail_search_range': 3,
        })
        return False

    def action_ai_analyze(self):
        """Send transaction details + found attachments to OpenAI and mark best matches."""
        self.ensure_one()

        attachments = self.gmail_found_attachment_ids
        if not attachments:
            raise UserError("Run Gmail search first — no attachments found to analyze.")

        config = self.env['openai.config'].sudo().search(
            [('company_id', '=', self.env.company.id)], limit=1
        )
        if not config or not config.api_key:
            raise UserError(
                "OpenAI is not configured.\n"
                "Go to Revolut Business API Integration → OpenAI Configuration."
            )

        att_lines = []
        for att in attachments:
            att_lines.append(
                f"ID={att.id} | Subject: {att.email_subject or '—'} | "
                f"From: {att.email_from or '—'} | Date: {att.email_date or '—'} | "
                f"File: {att.name or '—'} ({att.mime_type or '—'})"
            )

        prompt = (
            "You are a financial document assistant. "
            "Given a Revolut transaction, identify which of the following email attachments "
            "is the most likely invoice, receipt, or payment confirmation for that transaction.\n\n"
            f"Transaction:\n"
            f"  Description : {self.description or '—'}\n"
            f"  Amount      : {self.amount} {self.currency or ''}\n"
            f"  Merchant    : {self.merchant_name or '—'}\n"
            f"  Date        : {self.created_at.strftime('%Y-%m-%d') if self.created_at else '—'}\n"
            f"  Reference   : {self.reference or '—'}\n\n"
            "Email attachments found:\n"
            + "\n".join(att_lines)
            + "\n\n"
            "Respond ONLY with valid JSON — no markdown, no explanation:\n"
            '{"selections": [{"id": <integer>, "reason": "<brief reason>"}]}\n'
            "Include only attachments that clearly match. "
            'If none match, return: {"selections": []}'
        )

        payload = json.dumps({
            'model': config.model_name,
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': 300,
            'temperature': 0,
        }).encode()

        request = urllib.request.Request(
            'https://api.openai.com/v1/chat/completions',
            data=payload,
            headers=config._get_headers(),
            method='POST',
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            try:
                msg = json.loads(body).get('error', {}).get('message', body)
            except Exception:
                msg = body[:300]
            raise UserError(f"OpenAI API error: {msg}")
        except Exception as e:
            raise UserError(f"OpenAI request failed: {e}")

        raw = data.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
        try:
            result = json.loads(raw)
        except Exception:
            raise UserError(f"Could not parse OpenAI response:\n{raw[:500]}")

        selections = result.get('selections', [])
        selected_ids = {int(s['id']): s.get('reason', '') for s in selections}

        # Reset all, then mark selected
        attachments.write({'is_ai_selected': False, 'ai_selection_reason': False})
        for att in attachments:
            if att.id in selected_ids:
                att.write({
                    'is_ai_selected': True,
                    'ai_selection_reason': selected_ids[att.id],
                })

        return False

    # ── Sync action ───────────────────────────────────────────────────────────

    def action_sync_all_from_revolut(self):
        config = self.env['legacy.accounting.config'].sudo().search(
            [('company_id', '=', self.env.company.id)], limit=1
        )
        if not config or not config.access_token:
            raise UserError(
                'No access token found. '
                'Complete Step 4 in Revolut Business API Integration first.'
            )

        token = config.access_token.strip()
        accounts = self._revolut_get('/accounts', token)
        if not isinstance(accounts, list) or not accounts:
            raise UserError(
                'No accounts returned from Revolut API. '
                'Your access token may be invalid or expired.'
            )

        created_count = 0
        updated_count = 0

        for account in accounts:
            account_id = account.get('id')
            account_name = account.get('name') or account_id

            # Paginate through ALL transactions for this account.
            # API returns newest-first; to get older pages, pass `to` =
            # (oldest tx created_at - 1 ms) from previous batch.
            to_param = None

            while True:
                params = {'account': account_id, 'count': 1000}
                if to_param:
                    params['to'] = to_param

                transactions = self._revolut_get('/transactions', token, params=params)
                if not isinstance(transactions, list) or not transactions:
                    break

                for tx_data in transactions:
                    was_existing = self._upsert_transaction(tx_data, account_id, account_name)
                    if was_existing:
                        updated_count += 1
                    else:
                        created_count += 1

                # If fewer than 1000 returned, we've reached the beginning
                if len(transactions) < 1000:
                    break

                # Advance pagination cursor to just before the oldest transaction
                oldest_dt_str = transactions[-1].get('created_at', '')
                if not oldest_dt_str:
                    break
                try:
                    dt = datetime.datetime.fromisoformat(
                        oldest_dt_str.replace('Z', '+00:00')
                    )
                    dt = dt - datetime.timedelta(milliseconds=1)
                    to_param = dt.strftime('%Y-%m-%dT%H:%M:%S.') + \
                               f'{dt.microsecond // 1000:03d}Z'
                except Exception:
                    break

        total = created_count + updated_count
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Sync Complete',
                'message': (
                    f'Synced {total} transactions across {len(accounts)} account(s): '
                    f'{created_count} new, {updated_count} updated.'
                ),
                'type': 'success',
                'sticky': True,
            },
        }
