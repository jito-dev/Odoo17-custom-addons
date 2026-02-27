import base64
import html as _html
import logging
import re
from datetime import datetime, timedelta

from odoo import models, fields, api
from odoo.exceptions import UserError

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

_logger = logging.getLogger(__name__)

GMAIL_READONLY_SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'

# Month abbreviation map for mixed-input parsing
_MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
    'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
    'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}


def _parse_date_from_text(text):
    """Try to extract a date from free-form text.
    Returns (date_object, remaining_text) or (None, original_text).

    Supported formats (examples):
        17 Feb 2026        DD Mon[th] YYYY
        17 Feb, 2026       DD Mon, YYYY
        Feb 17 2026        Mon[th] DD YYYY
        Feb 17, 2026       Mon[th] DD, YYYY
        17 Feb             DD Mon  (year = current)
        Feb 17             Mon DD  (year = current)
        2026-02-17         YYYY-MM-DD
        2026/02/17         YYYY/MM/DD
        17/02/2026         DD/MM/YYYY
        17.02.2026         DD.MM.YYYY
        17-02-2026         DD-MM-YYYY
    """
    today = datetime.today()

    def _make(year, month, day):
        return datetime(int(year), int(month), int(day)).date()

    def _cut(m):
        return (text[:m.start()] + text[m.end():]).strip(' ,')

    # ── Pattern 1: "DD Mon[th] YYYY"  e.g.  "17 Feb 2026", "17 Feb, 2026"
    m = re.search(r'\b(\d{1,2})\s+([A-Za-z]{3,9})[,\s]+(\d{4})\b', text)
    if m:
        month_str = m.group(2)[:3].lower()
        if month_str in _MONTH_MAP:
            try:
                return _make(m.group(3), _MONTH_MAP[month_str], m.group(1)), _cut(m)
            except ValueError:
                pass

    # ── Pattern 2: "Mon[th] DD, YYYY"  e.g.  "Feb 17, 2026", "February 17 2026"
    m = re.search(r'\b([A-Za-z]{3,9})\s+(\d{1,2})[,\s]+(\d{4})\b', text)
    if m:
        month_str = m.group(1)[:3].lower()
        if month_str in _MONTH_MAP:
            try:
                return _make(m.group(3), _MONTH_MAP[month_str], m.group(2)), _cut(m)
            except ValueError:
                pass

    # ── Pattern 3: "YYYY-MM-DD" or "YYYY/MM/DD"
    m = re.search(r'\b(\d{4})[-/](\d{2})[-/](\d{2})\b', text)
    if m:
        try:
            return _make(m.group(1), m.group(2), m.group(3)), _cut(m)
        except ValueError:
            pass

    # ── Pattern 4: "DD/MM/YYYY", "DD.MM.YYYY", "DD-MM-YYYY"
    m = re.search(r'\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b', text)
    if m:
        try:
            return _make(m.group(3), m.group(2), m.group(1)), _cut(m)
        except ValueError:
            pass

    # ── Pattern 5: "DD Mon"  e.g.  "17 Feb"  (no year → current year)
    m = re.search(r'\b(\d{1,2})\s+([A-Za-z]{3,9})\b', text)
    if m:
        month_str = m.group(2)[:3].lower()
        if month_str in _MONTH_MAP:
            try:
                return _make(today.year, _MONTH_MAP[month_str], m.group(1)), _cut(m)
            except ValueError:
                pass

    # ── Pattern 6: "Mon DD"  e.g.  "Feb 17"  (no year → current year)
    m = re.search(r'\b([A-Za-z]{3,9})\s+(\d{1,2})\b', text)
    if m:
        month_str = m.group(1)[:3].lower()
        if month_str in _MONTH_MAP:
            try:
                return _make(today.year, _MONTH_MAP[month_str], m.group(2)), _cut(m)
            except ValueError:
                pass

    return None, text


def _format_size(size_bytes):
    """Return human-readable file size string."""
    if not size_bytes:
        return ''
    if size_bytes < 1024:
        return f'{size_bytes} B'
    if size_bytes < 1024 * 1024:
        return f'{size_bytes // 1024} KB'
    return f'{size_bytes / (1024 * 1024):.1f} MB'


# ── Card rendering helpers ─────────────────────────────────────────────────────

_AVATAR_COLORS = [
    '#1a73e8', '#34a853', '#ea4335', '#9c27b0',
    '#00796b', '#f4511e', '#039be5', '#8d6e63',
]

_LINK_KEYWORDS = frozenset([
    # Financial / document keywords
    'invoice', 'receipt', 'payment', 'download', 'pdf', 'bill',
    'statement', 'stripe', 'revolut', 'paypal', 'wise', 'document',
    'pay now', 'pay invoice', 'view invoice', 'get invoice',
    'order', 'transaction', 'checkout', 'purchase', 'subscription',
    'billing', 'account', 'refund', 'charge', 'transfer',
    'confirm', 'confirmation', 'summary', 'report',
    # Collaboration / communication services
    'github', 'gitlab', 'bitbucket',
    'slack', 'teams', 'discord',
    'meet', 'zoom', 'webex', 'whereby',
    'notion', 'confluence', 'jira',
    'drive', 'docs', 'sheets', 'dropbox', 'box.com',
    'loom', 'figma', 'miro',
    'trello', 'asana', 'monday',
    'linear', 'clickup',
])


def _extract_sender_name(sender_str):
    """Return display name from 'Name <email>' or the local part of the address."""
    m = re.match(r'^"?([^"<]+)"?\s*<', sender_str or '')
    if m:
        return m.group(1).strip()
    return (sender_str or '').split('@')[0]


def _prepare_email_html(html_content):
    """Strip document-level wrapper tags and unsafe elements for inline rendering."""
    if not html_content:
        return ''
    # Remove scripts (security) and style blocks (prevent CSS conflicts with Odoo)
    c = re.sub(r'<script\b[^>]*>.*?</script>', '', html_content,
               flags=re.DOTALL | re.IGNORECASE)
    c = re.sub(r'<style\b[^>]*>.*?</style>', '', c,
               flags=re.DOTALL | re.IGNORECASE)
    # Prefer <body> content only
    body_m = re.search(r'<body\b[^>]*>(.*?)</body>', c, re.DOTALL | re.IGNORECASE)
    if body_m:
        return body_m.group(1).strip()
    # Fallback: strip doctype / html / head wrappers
    c = re.sub(r'<!DOCTYPE[^>]*>', '', c, flags=re.IGNORECASE)
    c = re.sub(r'</?html\b[^>]*>', '', c, flags=re.IGNORECASE)
    c = re.sub(r'<head\b[^>]*>.*?</head>', '', c, flags=re.DOTALL | re.IGNORECASE)
    return c.strip()


def _extract_keyword_links(html_content):
    """Return up to 5 (url, label) pairs whose text or URL contains financial keywords.

    Handles quoted (single/double) and unquoted href attribute values.
    Returns at most 5 results, deduplicated by URL.
    """
    if not html_content:
        return []
    seen, result = set(), []
    # Match href with double quotes, single quotes, or no quotes (terminated by space/>)
    for m in re.finditer(
        r'<a\b[^>]*?\bhref=(?:"([^"]+)"|\'([^\']+)\'|([^\s>]+))[^>]*>(.*?)</a>',
        html_content, re.DOTALL | re.IGNORECASE,
    ):
        # Groups 1, 2, 3 correspond to double-quoted, single-quoted, unquoted href
        url = (m.group(1) or m.group(2) or m.group(3) or '').strip()
        label = ' '.join(re.sub(r'<[^>]+>', '', m.group(4)).split())[:80]
        if not url.startswith('http') or url in seen:
            continue
        combined = (url + ' ' + label).lower()
        if any(kw in combined for kw in _LINK_KEYWORDS):
            seen.add(url)
            result.append((url, label or url[:60]))
            if len(result) >= 5:
                break
    return result


class GoogleGmailSearchWizard(models.TransientModel):
    _name = 'google.gmail.search.wizard'
    _description = 'Gmail Email Search'

    # ── Input fields ──────────────────────────────────────────────────────────
    mixed_input = fields.Char(string='Quick Search (Date + Keywords)')
    search_keywords = fields.Char(string='Keywords')
    target_date = fields.Date(string='Date')
    with_attachment = fields.Boolean(string='With Attachment', default=True)
    search_range = fields.Integer(string='Date range (±days)', default=1)
    max_results = fields.Integer(string='Max Results', default=10)

    # ── Computed query display ─────────────────────────────────────────────────
    gmail_query = fields.Char(
        string='Gmail Query',
        compute='_compute_gmail_query',
        store=True,
    )
    date_range_display = fields.Char(
        string='Date Range',
        compute='_compute_gmail_query',
        store=True,
    )

    # ── All results (One2many) ─────────────────────────────────────────────────
    result_ids = fields.One2many(
        'google.gmail.search.result',
        'wizard_id',
        string='Results',
    )
    results_count = fields.Integer(string='Results Count', default=0)
    search_performed = fields.Boolean(default=False)

    # ── Navigation pointer ────────────────────────────────────────────────────
    current_result_id = fields.Many2one(
        'google.gmail.search.result',
        string='Current Email',
        ondelete='set null',
    )
    current_result_index = fields.Integer(string='Current Index', default=0)  # 0-based
    current_result_number = fields.Integer(
        string='Email #',
        compute='_compute_navigation_state',
        store=False,
    )
    can_go_prev = fields.Boolean(compute='_compute_navigation_state', store=False)
    can_go_next = fields.Boolean(compute='_compute_navigation_state', store=False)

    # ── Current email display (related) ───────────────────────────────────────
    current_subject = fields.Char(
        related='current_result_id.subject', string='Subject', readonly=True)
    current_sender = fields.Char(
        related='current_result_id.sender', string='From', readonly=True)
    current_to = fields.Char(
        related='current_result_id.to_field', string='To', readonly=True)
    current_cc = fields.Char(
        related='current_result_id.cc_field', string='CC', readonly=True)
    current_date_str = fields.Char(
        related='current_result_id.date', string='Date', readonly=True)
    current_body_html = fields.Html(
        related='current_result_id.body_html',
        string='Body',
        readonly=True,
        sanitize=False,
    )
    current_body_text = fields.Text(
        related='current_result_id.body_text', string='Body (Text)', readonly=True)
    current_snippet = fields.Char(
        related='current_result_id.snippet', string='Snippet', readonly=True)

    # ── All-at-once rendered HTML (replaces navigation) ───────────────────────
    results_html = fields.Html(
        string='Email Results',
        compute='_compute_results_html',
        store=False,
        sanitize=False,
    )

    # ── Current attachments (M2M, updated by navigation actions) ─────────────
    current_attachment_ids = fields.Many2many(
        'google.gmail.search.attachment',
        'revolut_gmail_wizard_att_rel',
        'wizard_id',
        'attachment_id',
        string='Attachments',
    )

    # ── Query computation ──────────────────────────────────────────────────────
    @api.depends('search_keywords', 'target_date', 'with_attachment', 'search_range')
    def _compute_gmail_query(self):
        for rec in self:
            parts = []
            if rec.search_keywords:
                parts.append(rec.search_keywords)
            if rec.with_attachment:
                parts.append('has:attachment')
            date_display = 'No date filter'
            if rec.target_date:
                start = rec.target_date - timedelta(days=rec.search_range)
                end = rec.target_date + timedelta(days=rec.search_range)
                parts.append(f'after:{start.strftime("%Y/%m/%d")}')
                parts.append(f'before:{end.strftime("%Y/%m/%d")}')
                date_display = (
                    f'Date range: {start} → {end} '
                    f'(±{rec.search_range} day(s) from {rec.target_date.strftime("%d %b %Y")})'
                )
            rec.gmail_query = ' '.join(parts)
            rec.date_range_display = date_display

    @api.depends('current_result_index', 'results_count')
    def _compute_navigation_state(self):
        for rec in self:
            rec.current_result_number = rec.current_result_index + 1
            rec.can_go_prev = rec.current_result_index > 0
            rec.can_go_next = rec.current_result_index < rec.results_count - 1

    # ── Computed HTML card list (Gmail-style) ─────────────────────────────────
    @api.depends(
        'result_ids',
        'result_ids.subject', 'result_ids.sender', 'result_ids.to_field',
        'result_ids.date', 'result_ids.snippet',
        'result_ids.body_html', 'result_ids.body_text',
        'result_ids.attachment_ids', 'result_ids.attachment_count',
    )
    def _compute_results_html(self):
        e = _html.escape
        for wizard in self:
            if not wizard.result_ids:
                wizard.results_html = ''
                continue

            cards = []
            for idx, result in enumerate(wizard.result_ids):

                # ── Header data ──────────────────────────────────────────────
                sender_name = _extract_sender_name(result.sender or '')
                avatar_letter = e((sender_name[0] if sender_name else '?').upper())
                avatar_color = _AVATAR_COLORS[idx % len(_AVATAR_COLORS)]
                sender_esc = e(result.sender or '—')
                subject_esc = e(result.subject or '(No Subject)')
                date_esc = e(result.date or '')

                # ── Email body ────────────────────────────────────────────────
                keyword_links = []
                if result.body_html:
                    body_inner = _prepare_email_html(result.body_html)
                    keyword_links = _extract_keyword_links(result.body_html)
                    body_content = (
                        f'<div style="font-size:13px;color:#202124;'
                        f'word-wrap:break-word;overflow-wrap:break-word;">'
                        f'{body_inner}</div>'
                    )
                elif result.body_text:
                    body_content = (
                        f'<div style="font-size:13px;color:#202124;'
                        f'white-space:pre-wrap;word-wrap:break-word;line-height:1.6;">'
                        f'{e(result.body_text)}</div>'
                    )
                else:
                    body_content = (
                        f'<div style="font-size:13px;color:#5f6368;font-style:italic;">'
                        f'{e(result.snippet or "")}</div>'
                    )

                # ── Attachments section — real download links via controller ──
                att_section = ''
                if result.attachment_count:
                    chips = ''.join(
                        f'<a href="/gmail/attachment/download/{att.id}"'
                        f' style="display:inline-flex;align-items:center;gap:6px;'
                        f'background:#fff;border:1px solid #c5cae9;border-radius:6px;'
                        f'padding:6px 12px;text-decoration:none;color:#202124;'
                        f'font-size:12px;box-shadow:0 1px 2px rgba(0,0,0,.06);margin:3px;">'
                        f'<span style="font-size:16px;">&#128196;</span>'
                        f'<span style="max-width:200px;overflow:hidden;text-overflow:ellipsis;'
                        f'white-space:nowrap;">{e(att.name or "file")}</span>'
                        f'<span style="background:#1a73e8;color:#fff;border-radius:3px;'
                        f'padding:1px 7px;font-size:11px;flex-shrink:0;">&#8595;&nbsp;Download</span>'
                        f'</a>'
                        for att in result.attachment_ids
                    )
                    att_section = (
                        f'<div style="padding:10px 16px;background:#f0f4ff;'
                        f'border-top:2px solid #c5cae9;">'
                        f'<div style="font-size:11px;font-weight:700;color:#3949ab;'
                        f'text-transform:uppercase;letter-spacing:0.6px;margin-bottom:8px;">'
                        f'&#128206;&nbsp;Attachments</div>'
                        f'<div style="display:flex;flex-wrap:wrap;">{chips}</div>'
                        f'</div>'
                    )

                # ── Relevant links section ────────────────────────────────────
                links_section = ''
                if keyword_links:
                    link_chips = ''.join(
                        f'<a href="{e(url)}" target="_blank" title="{e(url)}"'
                        f' style="display:inline-block;background:#e8f5e9;color:#2e7d32;'
                        f'border-radius:4px;padding:5px 11px;font-size:12px;'
                        f'text-decoration:none;border:1px solid #a5d6a7;'
                        f'max-width:260px;overflow:hidden;text-overflow:ellipsis;'
                        f'white-space:nowrap;vertical-align:middle;margin:3px;">'
                        f'{e(label)}</a>'
                        for url, label in keyword_links
                    )
                    links_section = (
                        f'<div style="padding:10px 16px;background:#f1f8f1;'
                        f'border-top:2px solid #a5d6a7;">'
                        f'<div style="font-size:11px;font-weight:700;color:#2e7d32;'
                        f'text-transform:uppercase;letter-spacing:0.6px;margin-bottom:8px;">'
                        f'&#128279;&nbsp;Relevant Links</div>'
                        f'<div style="display:flex;flex-wrap:wrap;">{link_chips}</div>'
                        f'</div>'
                    )

                card = (
                    # ── Card wrapper ──────────────────────────────────────────
                    f'<div style="border:1px solid #dadce0;border-radius:10px;'
                    f'margin-bottom:16px;overflow:hidden;background:#fff;'
                    f'box-shadow:0 1px 3px rgba(60,64,67,.12);">'

                    # ── Header: avatar + From / Subject / Date ────────────────
                    f'<div style="padding:12px 16px;background:#f8f9fa;'
                    f'border-bottom:1px solid #e8eaed;'
                    f'display:flex;align-items:center;gap:12px;">'

                    # Coloured avatar circle (sender initial)
                    f'<div style="width:38px;height:38px;border-radius:50%;'
                    f'background:{avatar_color};color:#fff;display:inline-flex;'
                    f'align-items:center;justify-content:center;font-size:16px;'
                    f'font-weight:700;flex-shrink:0;">{avatar_letter}</div>'

                    # From + Subject labels
                    f'<div style="flex:1;min-width:0;">'
                    f'<div style="font-size:13px;color:#202124;white-space:nowrap;'
                    f'overflow:hidden;text-overflow:ellipsis;">'
                    f'<span style="font-weight:600;color:#5f6368;margin-right:4px;">From:</span>'
                    f'{sender_esc}</div>'
                    f'<div style="font-size:13px;color:#202124;white-space:nowrap;'
                    f'overflow:hidden;text-overflow:ellipsis;margin-top:2px;">'
                    f'<span style="font-weight:600;color:#5f6368;margin-right:4px;">Subject:</span>'
                    f'<strong>{subject_esc}</strong></div>'
                    f'</div>'

                    # Date (top-right)
                    f'<div style="font-size:12px;color:#5f6368;white-space:nowrap;'
                    f'flex-shrink:0;align-self:flex-start;padding-top:2px;">'
                    f'<span style="font-weight:600;color:#5f6368;">Date:</span>&nbsp;{date_esc}</div>'
                    f'</div>'  # end header

                    # ── Body: rendered email HTML ─────────────────────────────
                    f'<div style="max-height:500px;overflow-y:auto;overflow-x:hidden;'
                    f'padding:14px 16px;border-bottom:1px solid #e8eaed;">'
                    f'{body_content}'
                    f'</div>'

                    # ── Attachments section ───────────────────────────────────
                    f'{att_section}'

                    # ── Relevant links section ────────────────────────────────
                    f'{links_section}'

                    f'</div>'  # end card
                )
                cards.append(card)

            wizard.results_html = (
                '<div class="gmail_cards_container" '
                'style="padding:0;margin:0;">'
                + '\n'.join(cards)
                + '</div>'
            )

    # ── Mixed input parser ─────────────────────────────────────────────────────
    @api.onchange('mixed_input')
    def _onchange_mixed_input(self):
        if not self.mixed_input:
            return
        parsed_date, keywords = _parse_date_from_text(self.mixed_input.strip())
        if parsed_date:
            self.target_date = parsed_date
        if keywords:
            self.search_keywords = keywords

    # ── Gmail service builder ──────────────────────────────────────────────────
    def _get_gmail_service(self):
        """Build and return an authenticated Gmail API v1 service for the current user."""
        self.ensure_one()
        user = self.env.user
        creds_record = user.sudo().google_drive_account_id
        if not creds_record or not creds_record._is_authorized():
            raise UserError(
                "Google account is not connected. "
                "Please connect your Google account via the Account Manager and "
                "make sure to grant Gmail access (re-connect if already connected before this update)."
            )

        get_param = self.env['ir.config_parameter'].sudo().get_param
        client_id = get_param('google_drive_client_id')
        client_secret = get_param('google_drive_client_secret')
        access_token = creds_record._get_valid_access_token()

        creds = Credentials(
            token=access_token,
            refresh_token=creds_record.sudo().refresh_token,
            token_uri='https://accounts.google.com/o/oauth2/token',
            client_id=client_id,
            client_secret=client_secret,
            scopes=[GMAIL_READONLY_SCOPE],
        )
        return build('gmail', 'v1', credentials=creds)

    # ── Main search action ─────────────────────────────────────────────────────
    def action_search_emails(self):
        self.ensure_one()

        # Clear previous results
        self.result_ids.unlink()
        self.write({
            'results_count': 0,
            'current_result_id': False,
            'current_result_index': 0,
            'current_attachment_ids': [(5,)],
            'search_performed': False,
        })

        service = self._get_gmail_service()
        query = self.gmail_query or ''
        max_res = max(1, min(self.max_results or 10, 50))

        try:
            response = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_res,
            ).execute()
        except Exception as exc:
            err = str(exc)
            if '403' in err or 'PERMISSION_DENIED' in err or 'insufficientPermissions' in err:
                raise UserError(
                    "Gmail access not authorized. Please reconnect your Google account "
                    "via Account Manager to grant Gmail (gmail.readonly) access."
                )
            raise UserError(f"Gmail API search failed: {exc}")

        messages = response.get('messages', [])
        self.write({'search_performed': True})

        if not messages:
            return self._return_form_action()

        result_records = []
        for msg_meta in messages:
            msg_id = msg_meta['id']
            try:
                msg = service.users().messages().get(
                    userId='me', id=msg_id, format='full'
                ).execute()
                result = self._parse_and_create_result(msg)
                result_records.append(result)
            except Exception as exc:
                _logger.warning("Failed to fetch Gmail message %s: %s", msg_id, exc)

        if result_records:
            first = result_records[0]
            self.write({
                'results_count': len(result_records),
                'current_result_id': first.id,
                'current_result_index': 0,
                'current_attachment_ids': [(6, 0, first.attachment_ids.ids)],
            })

        return self._return_form_action()

    # ── Navigation actions ─────────────────────────────────────────────────────
    def action_prev_result(self):
        self.ensure_one()
        if self.current_result_index > 0:
            new_idx = self.current_result_index - 1
            result = self.result_ids[new_idx]
            self.write({
                'current_result_index': new_idx,
                'current_result_id': result.id,
                'current_attachment_ids': [(6, 0, result.attachment_ids.ids)],
            })
        return self._return_form_action()

    def action_next_result(self):
        self.ensure_one()
        if self.current_result_index < self.results_count - 1:
            new_idx = self.current_result_index + 1
            result = self.result_ids[new_idx]
            self.write({
                'current_result_index': new_idx,
                'current_result_id': result.id,
                'current_attachment_ids': [(6, 0, result.attachment_ids.ids)],
            })
        return self._return_form_action()

    def action_clear_search(self):
        self.ensure_one()
        self.result_ids.unlink()
        self.write({
            'mixed_input': False,
            'search_keywords': False,
            'target_date': False,
            'with_attachment': True,
            'search_range': 1,
            'max_results': 10,
            'results_count': 0,
            'current_result_id': False,
            'current_result_index': 0,
            'current_attachment_ids': [(5,)],
            'search_performed': False,
        })
        return self._return_form_action()

    def _return_form_action(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ── Message parsing helpers ────────────────────────────────────────────────
    def _parse_and_create_result(self, msg):
        msg_id = msg['id']
        payload = msg.get('payload', {})
        headers = {h['name'].lower(): h['value'] for h in payload.get('headers', [])}

        subject = headers.get('subject', '(No Subject)')
        sender = headers.get('from', '')
        to_field = headers.get('to', '')
        cc_field = headers.get('cc', '')
        date_str = headers.get('date', '')
        snippet = msg.get('snippet', '')

        body_html, body_text = self._extract_body(payload)

        result = self.env['google.gmail.search.result'].create({
            'wizard_id': self.id,
            'message_id': msg_id,
            'subject': subject,
            'sender': sender,
            'to_field': to_field,
            'cc_field': cc_field,
            'date': date_str,
            'snippet': snippet,
            'body_html': body_html,
            'body_text': body_text,
        })

        self._create_attachments(msg_id, payload, result)
        return result

    def _extract_body(self, payload):
        """Recursively extract HTML and plain-text body from Gmail payload."""
        html_body = ''
        text_body = ''

        def decode_data(data):
            if data:
                # Gmail uses url-safe base64; pad to multiple of 4
                padded = data + '=' * (-len(data) % 4)
                return base64.urlsafe_b64decode(padded).decode('utf-8', errors='replace')
            return ''

        def process_part(part):
            nonlocal html_body, text_body
            mime = part.get('mimeType', '')
            body_data = part.get('body', {}).get('data', '')

            if mime == 'text/html' and not html_body:
                html_body = decode_data(body_data)
            elif mime == 'text/plain' and not text_body:
                text_body = decode_data(body_data)
            elif mime.startswith('multipart/'):
                for subpart in part.get('parts', []):
                    process_part(subpart)

        process_part(payload)
        return html_body, text_body

    def _create_attachments(self, msg_id, payload, result):
        """Recursively find attachment parts and create attachment records."""
        def find_attachments(part):
            filename = part.get('filename')
            att_id = part.get('body', {}).get('attachmentId')
            if filename and att_id:
                size = part.get('body', {}).get('size', 0)
                self.env['google.gmail.search.attachment'].create({
                    'result_id': result.id,
                    'gmail_attachment_id': att_id,
                    'gmail_message_id': msg_id,
                    'name': filename,
                    'mime_type': part.get('mimeType', 'application/octet-stream'),
                    'size': size,
                    'size_display': _format_size(size),
                })
            for subpart in part.get('parts', []):
                find_attachments(subpart)

        find_attachments(payload)


# ── Result model ───────────────────────────────────────────────────────────────

class GoogleGmailSearchResult(models.TransientModel):
    _name = 'google.gmail.search.result'
    _description = 'Gmail Search Result'

    wizard_id = fields.Many2one('google.gmail.search.wizard', ondelete='cascade')
    message_id = fields.Char(string='Gmail Message ID')

    subject = fields.Char(string='Subject')
    sender = fields.Char(string='From')
    to_field = fields.Char(string='To')
    cc_field = fields.Char(string='CC')
    date = fields.Char(string='Date')
    snippet = fields.Char(string='Snippet')

    body_html = fields.Html(string='Body HTML', sanitize=False)
    body_text = fields.Text(string='Body Text')

    attachment_ids = fields.One2many(
        'google.gmail.search.attachment',
        'result_id',
        string='Attachments',
    )
    attachment_count = fields.Integer(
        string='Attachments',
        compute='_compute_attachment_count',
        store=True,
    )

    @api.depends('attachment_ids')
    def _compute_attachment_count(self):
        for rec in self:
            rec.attachment_count = len(rec.attachment_ids)


# ── Attachment model ───────────────────────────────────────────────────────────

class GoogleGmailSearchAttachment(models.TransientModel):
    _name = 'google.gmail.search.attachment'
    _description = 'Gmail Attachment'

    result_id = fields.Many2one('google.gmail.search.result', ondelete='cascade')
    gmail_attachment_id = fields.Char(string='Google Attachment ID')
    gmail_message_id = fields.Char(string='Gmail Message ID')

    name = fields.Char(string='File Name')
    mime_type = fields.Char(string='Type')
    size = fields.Integer(string='Size (bytes)')
    size_display = fields.Char(string='Size')

    def action_download(self):
        """Stream the Gmail attachment directly to the browser via the download controller.

        No data is stored in Odoo or the database — the file is fetched from
        Gmail and streamed on-demand by the controller endpoint.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/gmail/attachment/download/{self.id}',
            'target': 'new',
        }
