# Copyright © 2024 Garazd Creation (https://garazd.biz)
# @author: Yurii Razumovskyi (support@garazd.biz)
# @author: Iryna Razumovska (support@garazd.biz)
# License OPL-1 (https://www.odoo.com/documentation/17.0/legal/licenses.html).

import datetime
import logging

from odoo import api, models
from odoo.tools.safe_eval import dateutil

_logger = logging.getLogger(__name__)


class HrJob(models.Model):
    _inherit = "hr.job"

    @api.model
    def convert_iso_date(self, value, null_date_value: str = None) -> datetime.datetime or None:
        """
        Convert the string to datetime.datetime.
        :param value: datetime string value;
        :param null_date_value: a sample of the null value, if value equals it, return None.
        """
        if null_date_value and value == null_date_value:
            return None
        return dateutil.parser.isoparse(value)
