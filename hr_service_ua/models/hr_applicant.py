# Copyright © 2024 Garazd Creation (https://garazd.biz)
# @author: Yurii Razumovskyi (support@garazd.biz)
# @author: Iryna Razumovska (support@garazd.biz)
# License OPL-1 (https://www.odoo.com/documentation/17.0/legal/licenses.html).

import base64
from typing import Dict
import requests

from odoo import models


class HrApplicant(models.Model):
    _name = 'hr.applicant'
    _inherit = ['hr.applicant', 'avatar.mixin']

    def download_and_set_photo(self, photo_url: str):
        """ Upload candidate photo while resume parsing. """
        self.ensure_one()
        response = requests.get(photo_url, timeout=10)
        if response.ok:
            self.image_1920 = base64.b64encode(response.content)

    def download_and_link_attachment(self, url: str, headers: Dict = None, auth: Dict = None):
        self.ensure_one()
        # Check that attachment was not created before
        if not self.env['ir.attachment'].search_count([
                ('url', '=', url), ('res_model', '=', 'hr.applicant'), ('res_id', '=', self.id),
        ]):
            response = requests.get(url=url, auth=auth, headers=headers, timeout=10)
            if response.ok:
                self.env['ir.attachment'].create({
                    'name': 'CV: %s' % self.name,
                    'res_model': 'hr.applicant',
                    'res_id': self.id,
                    'datas': base64.b64encode(response.content),
                    'url': url,
                })
