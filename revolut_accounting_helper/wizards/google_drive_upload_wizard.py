from odoo import models, fields, api
from odoo.exceptions import UserError
import re

class GoogleDriveUploadWizard(models.TransientModel):
    _name = 'google.drive.upload.wizard'

    folder_input = fields.Char(
        string='Target folder', 
        required=True, 
    )

    file_data = fields.Binary(string='File', required=True)
    file_name = fields.Char(string='File name')

    state = fields.Selection([
        ('draft', 'Preparation'),
        ('done', 'Uploaded')
    ], string='Status', default='draft')
    
    result_link = fields.Char(string='Link to file', readonly=True)

    def action_upload_file(self):
        self.ensure_one()
        
        folder_id = self._extract_folder_id(self.folder_input)
        if not folder_id:
            raise UserError('Failed to get folder id')

        # TODO GOOGLE API AUTH
        # ...
        # uploaded_file_url = service.files().create(...)
        
        uploaded_file_url = f"https://drive.google.com/file/d/1xhB-hFXh6oeFDQJNAKLWzfLtwvB271mC/view?usp=drive_link"

        self.write({
            'state': 'done',
            'result_link': uploaded_file_url
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