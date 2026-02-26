import base64
import io
import re

from werkzeug import urls as werkzeug_urls

from odoo import api, models, fields, Command, _
from odoo.exceptions import UserError

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

GOOGLE_AUTH_ENDPOINT = 'https://accounts.google.com/o/oauth2/auth'
GOOGLE_DRIVE_SCOPE = ' '.join([
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/userinfo.email',
])


class GoogleDriveUploadWizard(models.TransientModel):
    _name = 'google.drive.upload.wizard'
    _description = 'Google Drive Upload Wizard'

    folder_input = fields.Char(
        string='Target folder',
        required=False,
    )
    file_data = fields.Binary(string='File', required=False)
    file_name = fields.Char(string='File name')

    state = fields.Selection([
        ('not_connected', 'Not Connected'),
        ('draft', 'Ready'),
        ('done', 'Uploaded'),
    ], string='Status', default='not_connected')

    result_link = fields.Char(string='Link to file', readonly=True)
    save_as_default = fields.Boolean(string='Save as default folder', default=False)

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        user = self.env.user
        creds = user.google_drive_account_id
        if creds and creds._is_authorized():
            defaults['state'] = 'draft'
            google_email = creds.sudo().google_email
            saved_folder = self.env['google.drive.folder.config']._get_default_folder(
                self.env, user.id, google_email
            )
            if saved_folder:
                defaults['folder_input'] = saved_folder
        else:
            defaults['state'] = 'not_connected'
        return defaults

    def action_connect_google_drive(self):
        self.ensure_one()
        get_param = self.env['ir.config_parameter'].sudo().get_param
        client_id = get_param('google_drive_client_id')
        if not client_id:
            raise UserError(_(
                "Google Drive is not configured. "
                "Please ask your administrator to set the Client ID and Secret in Settings."
            ))
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url').rstrip('/')
        redirect_uri = f'{base_url}/google/drive/callback'
        params = {
            'response_type': 'code',
            'client_id': client_id,
            'scope': GOOGLE_DRIVE_SCOPE,
            'redirect_uri': redirect_uri,
            'access_type': 'offline',
            'prompt': 'consent',
        }
        auth_url = f'{GOOGLE_AUTH_ENDPOINT}?{werkzeug_urls.url_encode(params)}'
        return {
            'type': 'ir.actions.act_url',
            'url': auth_url,
            'target': 'new',
        }

    def action_check_connection(self):
        self.ensure_one()
        user = self.env.user
        creds = user.google_drive_account_id
        if creds and creds._is_authorized():
            self.state = 'draft'
        else:
            self.state = 'not_connected'
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_upload_file(self):
        self.ensure_one()

        if not self.folder_input:
            raise UserError(_("Please enter a target folder URL or ID."))
        if not self.file_data:
            raise UserError(_("Please select a file to upload."))

        folder_id = self._extract_folder_id(self.folder_input)
        if not folder_id:
            raise UserError(_("Failed to extract folder ID from the provided input."))

        user = self.env.user
        creds_record = user.google_drive_account_id
        if not creds_record or not creds_record._is_authorized():
            raise UserError(_("Google Drive is not connected. Please connect your account first."))

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
        )

        try:
            service = build('drive', 'v3', credentials=creds)

            file_content = base64.b64decode(self.file_data)
            file_stream = io.BytesIO(file_content)
            media = MediaIoBaseUpload(
                file_stream,
                mimetype='application/octet-stream',
                resumable=True,
            )

            file_metadata = {
                'name': self.file_name or 'Untitled',
                'parents': [folder_id],
            }

            uploaded_file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink',
            ).execute()

            uploaded_file_url = uploaded_file.get('webViewLink')

        except Exception as exc:
            raise UserError(_("Upload error. Details: %s", str(exc)))

        if self.save_as_default:
            google_email = creds_record.sudo().google_email
            self.env['google.drive.folder.config']._save_default_folder(
                self.env, user.id, google_email, self.folder_input
            )

        self.write({
            'state': 'done',
            'result_link': uploaded_file_url,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _extract_folder_id(self, folder_input):
        if "drive.google.com" in folder_input:
            match = re.search(r'/folders/([a-zA-Z0-9-_]+)', folder_input)
            if match:
                return match.group(1)
            return False
        return folder_input
