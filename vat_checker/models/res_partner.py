# -*- coding: utf-8 -*-
import json
import logging
import re
import urllib.request
import urllib.error

from odoo import models, fields, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Mapping of EU country names to VIES 2-letter member state codes
VIES_COUNTRY_CODES = {
    "AT": "AT",  # Austria
    "BE": "BE",  # Belgium
    "BG": "BG",  # Bulgaria
    "CY": "CY",  # Cyprus
    "CZ": "CZ",  # Czechia
    "DE": "DE",  # Germany
    "DK": "DK",  # Denmark
    "EE": "EE",  # Estonia
    "EL": "EL",  # Greece
    "ES": "ES",  # Spain
    "FI": "FI",  # Finland
    "FR": "FR",  # France
    "HR": "HR",  # Croatia
    "HU": "HU",  # Hungary
    "IE": "IE",  # Ireland
    "IT": "IT",  # Italy
    "LT": "LT",  # Lithuania
    "LU": "LU",  # Luxembourg
    "LV": "LV",  # Latvia
    "MT": "MT",  # Malta
    "NL": "NL",  # The Netherlands
    "PL": "PL",  # Poland
    "PT": "PT",  # Portugal
    "RO": "RO",  # Romania
    "SE": "SE",  # Sweden
    "SI": "SI",  # Slovenia
    "SK": "SK",  # Slovakia
    "XI": "XI",  # Northern Ireland
}

VIES_API_BASE = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{ms}/vat/{vat}"


class ResPartner(models.Model):
    _inherit = "res.partner"

    # VAT check result fields
    vat_check_valid = fields.Boolean(
        string="VAT Valid",
        readonly=True,
        copy=False,
    )
    vat_check_date = fields.Datetime(
        string="VAT Check Date",
        readonly=True,
        copy=False,
    )
    vat_check_name = fields.Char(
        string="Registered Name",
        readonly=True,
        copy=False,
    )
    vat_check_address = fields.Text(
        string="Registered Address",
        readonly=True,
        copy=False,
    )
    vat_check_user_error = fields.Char(
        string="VIES Status",
        readonly=True,
        copy=False,
    )
    vat_check_request_id = fields.Char(
        string="VIES Request ID",
        readonly=True,
        copy=False,
    )
    vat_check_original_vat = fields.Char(
        string="Checked VAT Number",
        readonly=True,
        copy=False,
    )

    def _parse_vat_number(self, vat):
        """
        Split a VAT string into (member_state_code, vat_number).

        Expects the first 2 characters to be the EU member state code and the
        remainder to be the numeric/alphanumeric VAT number.  Whitespace is
        stripped and the code is upper-cased before matching against the
        supported VIES member states.

        Returns (ms_code, number) or raises UserError.
        """
        if not vat:
            raise UserError(_("Please enter a Tax ID before requesting VAT information."))

        vat_clean = re.sub(r"\s+", "", vat).upper()

        if len(vat_clean) < 3:
            raise UserError(
                _(
                    "The Tax ID '%s' is too short. "
                    "It must start with a 2-letter EU country code followed by the VAT number "
                    "(e.g. PL6793294352)."
                )
                % vat
            )

        ms_code = vat_clean[:2]
        number = vat_clean[2:]

        if ms_code not in VIES_COUNTRY_CODES:
            raise UserError(
                _(
                    "The country code '%s' is not a supported EU VIES member state. "
                    "Supported codes are: %s"
                )
                % (ms_code, ", ".join(sorted(VIES_COUNTRY_CODES.keys())))
            )

        if not number:
            raise UserError(
                _("The Tax ID '%s' does not contain a VAT number after the country code.")
                % vat
            )

        return ms_code, number

    def action_check_vat(self):
        """Call the VIES REST API and persist the result on the partner record."""
        self.ensure_one()

        ms_code, vat_number = self._parse_vat_number(self.vat)

        url = VIES_API_BASE.format(ms=ms_code, vat=vat_number)
        _logger.info("Calling VIES API: %s", url)

        try:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                raw = response.read().decode("utf-8")
                data = json.loads(raw)
        except urllib.error.HTTPError as exc:
            _logger.warning("VIES API HTTP error %s for URL %s", exc.code, url)
            raise UserError(
                _("VIES service returned an error (HTTP %s). Please try again later.") % exc.code
            ) from exc
        except urllib.error.URLError as exc:
            _logger.warning("VIES API connection error for URL %s: %s", url, exc.reason)
            raise UserError(
                _("Could not reach the VIES service: %s. Please check your internet connection.") % exc.reason
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            _logger.warning("VIES API invalid response for URL %s", url)
            raise UserError(
                _("The VIES service returned an unexpected response. Please try again later.")
            ) from exc

        is_valid = data.get("isValid", False)

        self.write(
            {
                "vat_check_valid": is_valid,
                "vat_check_date": fields.Datetime.now(),
                "vat_check_name": data.get("name") or "",
                "vat_check_address": data.get("address") or "",
                "vat_check_user_error": data.get("userError") or "",
                "vat_check_request_id": data.get("requestIdentifier") or "",
                "vat_check_original_vat": data.get("originalVatNumber") or vat_number,
            }
        )

        if is_valid:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("VAT Valid"),
                    "message": _(
                        "VAT number %s%s is valid. Company: %s"
                    ) % (ms_code, vat_number, data.get("name", "")),
                    "type": "success",
                    "sticky": False,
                },
            }
        else:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("VAT Invalid"),
                    "message": _(
                        "VAT number %s%s could not be verified in the VIES database."
                    ) % (ms_code, vat_number),
                    "type": "warning",
                    "sticky": False,
                },
            }
