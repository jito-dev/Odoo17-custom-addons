import base64
import logging

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RevolutGmailAttachment(models.Model):
    _name = 'revolut.gmail.attachment'
    _description = 'Gmail Attachment found for Revolut Transaction'
    _order = 'email_date desc, name'

    transaction_id = fields.Many2one(
        'revolut.transaction',
        string='Transaction',
        ondelete='cascade',
        required=True,
        index=True,
    )
    message_record_id = fields.Many2one(
        'revolut.gmail.message',
        string='Gmail Message',
        ondelete='cascade',
        index=True,
    )
    gmail_message_id = fields.Char(string='Gmail Message ID', required=True)
    gmail_attachment_id = fields.Char(string='Gmail Attachment ID', required=True)
    name = fields.Char(string='Filename', required=True)
    mime_type = fields.Char(string='MIME Type')
    size_display = fields.Char(string='Size')
    email_subject = fields.Char(string='Subject')
    email_from = fields.Char(string='From')
    email_date = fields.Char(string='Email Date')
    is_attached = fields.Boolean(string='Attached', default=False)
    is_ai_selected = fields.Boolean(string='AI Selected', default=False)
    ai_selection_reason = fields.Char(string='AI Reason', readonly=True)

    def _get_gmail_service(self):
        """Build an authenticated Gmail API service for the current user."""
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError:
            raise UserError(_(
                "Google API client libraries are not installed.\n"
                "Please install them: pip install google-api-python-client google-auth"
            ))

        user = self.env.user
        creds_record = user.sudo().google_account_id
        if not creds_record or not creds_record._is_authorized():
            raise UserError(_(
                "Google account is not connected. "
                "Please connect via Revolut Business API Integration → Google / Gmail Setup."
            ))

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

    def action_preview(self):
        """Open the Gmail attachment in a new browser tab for preview/download."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/revolut/gmail/attachment/preview/{self.id}',
            'target': 'new',
        }

    def action_attach(self):
        """Download the Gmail attachment and link it to the transaction."""
        self.ensure_one()
        service = self._get_gmail_service()

        try:
            att_response = service.users().messages().attachments().get(
                userId='me',
                messageId=self.gmail_message_id,
                id=self.gmail_attachment_id,
            ).execute()
        except Exception as exc:
            raise UserError(_("Failed to download Gmail attachment: %s", str(exc)))

        raw_data = att_response.get('data', '')
        padded = raw_data + '=' * (-len(raw_data) % 4)
        file_bytes = base64.urlsafe_b64decode(padded)

        attachment = self.env['ir.attachment'].create({
            'name': self.name,
            'type': 'binary',
            'datas': base64.b64encode(file_bytes),
            'mimetype': self.mime_type or 'application/octet-stream',
        })

        self.transaction_id.write({
            'invoice_attachment_ids': [(4, attachment.id)],
        })
        self.is_attached = True

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Attached'),
                'message': _('"%s" has been attached to the transaction.', self.name),
                'type': 'success',
                'sticky': False,
            },
        }
