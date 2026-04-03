import logging
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class RevolutGmailMessage(models.Model):
    _name = 'revolut.gmail.message'
    _description = 'Gmail Message found for Revolut Transaction'
    _order = 'email_date desc, id desc'

    transaction_id = fields.Many2one(
        'revolut.transaction',
        string='Transaction',
        ondelete='cascade',
        required=True,
        index=True,
    )
    gmail_message_id = fields.Char(string='Gmail Message ID', required=True)
    subject = fields.Char(string='Subject')
    sender = fields.Char(string='From')
    email_date = fields.Char(string='Date')
    snippet = fields.Text(string='Snippet')
    body_html = fields.Html(string='Email Body (HTML)', sanitize=False)
    body_text = fields.Text(string='Email Body (Text)')
    attachment_count = fields.Integer(string='Attachments', default=0)
    attachment_ids = fields.One2many(
        'revolut.gmail.attachment',
        'message_record_id',
        string='Attachments',
    )
    link_ids = fields.One2many(
        'revolut.gmail.link',
        'message_id',
        string='Detected Links',
    )
    link_count = fields.Integer(
        string='Links',
        compute='_compute_link_count',
    )

    @api.depends('link_ids')
    def _compute_link_count(self):
        for rec in self:
            rec.link_count = len(rec.link_ids)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_view_email(self):
        """Open the full email in a popup dialog."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.subject or 'Email',
            'res_model': 'revolut.gmail.message',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref(
                'legacy_accounting_helper.view_revolut_gmail_message_form'
            ).id,
            'target': 'new',
        }

    # ------------------------------------------------------------------
    # Link extraction + heuristic scoring
    # ------------------------------------------------------------------

    @staticmethod
    def extract_and_score_links(body_html, body_text):
        """Extract all links from email body and score by invoice likelihood.

        Returns list of dicts sorted by score descending:
        [{'url': str, 'text': str, 'score': int, 'reasons': [str]}, ...]
        """
        links = {}  # url -> {url, text, score, reasons}

        # -- Extract <a href> from HTML --
        class _LinkExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.current_href = None
                self.current_text = ''

            def handle_starttag(self, tag, attrs):
                if tag == 'a':
                    attrs_dict = dict(attrs)
                    href = (attrs_dict.get('href') or '').strip()
                    if href and href.startswith(('http://', 'https://')):
                        self.current_href = href
                        self.current_text = ''

            def handle_data(self, data):
                if self.current_href is not None:
                    self.current_text += data

            def handle_endtag(self, tag):
                if tag == 'a' and self.current_href:
                    url = self.current_href
                    text = self.current_text.strip()
                    if url not in links:
                        links[url] = {
                            'url': url, 'text': text,
                            'score': 0, 'reasons': [],
                        }
                    elif text and not links[url].get('text'):
                        links[url]['text'] = text
                    self.current_href = None
                    self.current_text = ''

        if body_html:
            try:
                parser = _LinkExtractor()
                parser.feed(body_html)
            except Exception:
                pass

        # -- Extract bare URLs from plain text --
        if body_text:
            url_re = re.compile(r'https?://[^\s<>"\'`\]\)]+')
            for match in url_re.finditer(body_text):
                url = match.group(0).rstrip('.,;:!?)')
                if url not in links:
                    links[url] = {
                        'url': url, 'text': '',
                        'score': 0, 'reasons': [],
                    }

        if not links:
            return []

        # -- Scoring constants --
        SOCIAL_DOMAINS = {
            'facebook.com', 'twitter.com', 'linkedin.com', 'instagram.com',
            'youtube.com', 'tiktok.com', 'pinterest.com', 'x.com',
            'reddit.com', 'tumblr.com',
        }
        MARKETING_DOMAINS = {
            'mailchimp.com', 'hubspot.com', 'sendgrid.net', 'mailgun.org',
            'constantcontact.com', 'campaign-archive.com', 'list-manage.com',
            'mailtrack.io', 'click.mailerlite.com',
        }
        INVOICE_KW = ['invoice', 'receipt', 'bill', 'billing', 'factura']
        DOWNLOAD_KW = ['download', 'attachment', 'file', 'document', 'doc']
        PAYMENT_KW = ['statement', 'order', 'payment', 'confirmation',
                      'transaction', 'purchase']
        NEGATIVE_PATTERNS = [
            'unsubscribe', 'opt-out', 'optout', 'preference',
            'privacy', 'terms-of', 'terms_of', 'legal', 'cookie',
            'gdpr', 'manage-subscription', 'email-preferences',
        ]

        for url, ld in links.items():
            score = 0
            reasons = []
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            path_lower = parsed.path.lower()
            query_lower = (parsed.query or '').lower()
            full_lower = url.lower()
            text_lower = (ld.get('text') or '').lower()

            # Strong positive: invoice keywords in URL
            for kw in INVOICE_KW:
                if kw in path_lower or kw in query_lower:
                    score += 10
                    reasons.append(f'URL contains "{kw}"')
                    break

            # Positive: direct PDF link
            if path_lower.endswith('.pdf'):
                score += 8
                reasons.append('Direct PDF link')

            # Positive: download/file indicators in URL
            for kw in DOWNLOAD_KW:
                if kw in path_lower or kw in query_lower:
                    score += 5
                    reasons.append(f'URL contains "{kw}"')
                    break

            # Weak positive: link text contains relevant keywords
            for kw in INVOICE_KW + ['download', 'view', 'open', 'pdf']:
                if kw in text_lower:
                    score += 3
                    reasons.append(f'Link text: "{kw}"')
                    break

            # Weak positive: payment-related keywords in URL
            for kw in PAYMENT_KW:
                if kw in path_lower or kw in query_lower:
                    score += 2
                    reasons.append(f'URL contains "{kw}"')
                    break

            # Negative: social media
            if any(s in domain for s in SOCIAL_DOMAINS):
                score -= 10
                reasons.append('Social media')

            # Negative: marketing / tracking domains
            if any(m in domain for m in MARKETING_DOMAINS):
                score -= 5
                reasons.append('Marketing/tracking')

            # Negative: unsubscribe / legal
            for neg in NEGATIVE_PATTERNS:
                if neg in full_lower:
                    score -= 8
                    reasons.append(f'"{neg}" pattern')
                    break

            # Negative: image / tracking pixel
            if any(path_lower.endswith(ext)
                   for ext in ('.gif', '.png', '.jpg', '.jpeg', '.svg', '.ico')):
                score -= 5
                reasons.append('Image/pixel')

            ld['score'] = score
            ld['reasons'] = reasons

        return sorted(links.values(), key=lambda x: -x['score'])

    def create_link_records(self, links_data):
        """Create revolut.gmail.link records from scored link dicts."""
        GmailLink = self.env['revolut.gmail.link']
        for ld in links_data:
            GmailLink.create({
                'message_id': self.id,
                'url': ld.get('url', ''),
                'link_text': ld.get('text', '') or '',
                'score': ld.get('score', 0),
                'match_reasons': ', '.join(ld.get('reasons', [])),
            })
