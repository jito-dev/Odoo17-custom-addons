import logging

from odoo import _, models
from odoo.tools.misc import formatLang

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    # === BUSINESS METHODS - PORTAL TRANSFER DETAILS === #

    def _get_transfer_provider(self):
        """ Return the Wire Transfer provider this invoice can be paid through, if any.

        Note: `self.ensure_one()`

        :return: The provider, empty when bank transfer is not offered for this invoice.
        :rtype: recordset of `payment.provider`
        """
        self.ensure_one()

        providers = self.env['payment.provider'].sudo().search([
            ('code', '=', 'custom'),
            ('custom_mode', '=', 'wire_transfer'),
            ('state', 'in', ('enabled', 'test')),
            ('company_id', '=', self.company_id.id),
        ])
        # An empty currency list means "any currency", which is how Odoo reads it everywhere else.
        return providers.filtered(
            lambda p: not p.available_currency_ids or self.currency_id in p.available_currency_ids
        )[:1]

    def _get_transfer_details(self):
        """ Return everything the customer needs to send a bank transfer for this invoice.

        Read from the invoice at display time and never stored: change the Recipient Bank and the
        card follows on the next page load.

        Two values are deliberately not what they look like. The amount is `amount_residual`, not
        the total: after a partial payment the customer must be told what is *left*, or they
        overpay. And every row carries a separate `copy` value where what reads well and what a
        bank form accepts are not the same string — a bank rejects "2,320.00 USD" in an amount
        field and often rejects the spaces in a grouped IBAN.

        Note: `self.ensure_one()`

        :return: The rows to display, or an empty list when the details are incomplete.
        :rtype: list
        """
        self.ensure_one()

        bank = self.partner_bank_id
        provider = self._get_transfer_provider()
        if not provider:
            return []

        # A half-filled block is worse than none: a transfer sent without a BIC is refused by the
        # correspondent bank or sits in limbo for weeks, and the customer has no way to know that
        # the dash they saw was a missing setting rather than "not needed for this bank".
        missing = []
        if not bank:
            missing.append('no Recipient Bank on the invoice')
        else:
            if not bank.acc_number:
                missing.append('the bank account has no number')
            if not bank.bank_id:
                missing.append('the bank account is not linked to a bank')
            elif not bank.bank_id.bic:
                missing.append(f'the bank {bank.bank_id.name} has no BIC')
        if missing:
            _logger.info(
                "Not showing the bank transfer details on the portal page of %s: %s. Fill them in "
                "on the invoice and on the bank account for this invoice to be payable by "
                "transfer.", self.display_name, '; '.join(missing)
            )
            return []

        company_partner = self.company_id.partner_id
        reference = self.payment_reference or self.name
        purpose = (provider.transfer_purpose_template or '').replace('{reference}', reference)
        amount = self.currency_id.round(self.amount_residual)

        rows = [{
            'key': 'amount',
            'label': _("Amount to pay"),
            # The ISO code, not the symbol: "$" is three different currencies, and this number
            # is retyped into an international transfer form.
            'value': f'{formatLang(self.env, amount, currency_obj=None, digits=self.currency_id.decimal_places)}'
                     f' {self.currency_id.name}',
            # A bank amount field takes digits, not a grouped and suffixed string.
            'copy': f'{amount:.{self.currency_id.decimal_places}f}',
            'icon': 'amount',
            'accent': True,
            'mono': True,
        }, {
            'key': 'holder',
            'label': _("Account holder"),
            'value': company_partner.name,
            'icon': 'holder',
            'section': _("Beneficiary"),
        }, {
            'key': 'address',
            'label': _("Address"),
            'value': self._transfer_format_address(company_partner),
            'icon': 'address',
        }]
        if company_partner.vat:
            rows.append({
                'key': 'vat',
                'label': _("VAT (Tax ID)"),
                'value': company_partner.vat,
                'icon': 'vat',
                'mono': True,
            })

        rows += [{
            'key': 'iban',
            'label': _("Account number (IBAN)"),
            'value': bank.acc_number,
            # Grouped for reading, unspaced for pasting: many bank forms refuse the spaces.
            'copy': bank.acc_number.replace(' ', ''),
            'icon': 'iban',
            'mono': True,
            'section': _("Payment details"),
        }, {
            'key': 'bic',
            'label': _("SWIFT / BIC"),
            'value': bank.bank_id.bic,
            'icon': 'bic',
            'mono': True,
        }, {
            'key': 'bank_name',
            'label': _("Bank name"),
            'value': bank.bank_id.name,
            'icon': 'bank',
        }]
        bank_address = self._transfer_format_address(bank.bank_id)
        if bank_address:
            rows.append({
                'key': 'bank_address',
                'label': _("Bank address"),
                'value': bank_address,
                'icon': 'address',
            })

        rows.append({
            'key': 'reference',
            'label': _("Payment reference"),
            'value': reference,
            'icon': 'reference',
            'mono': True,
            'section': _("Reference"),
        })
        if purpose:
            rows.append({
                'key': 'purpose',
                'label': _("Payment purpose"),
                'value': purpose,
                'icon': 'purpose',
            })

        for row in rows:
            row.setdefault('copy', row['value'])
        return rows

    @staticmethod
    def _transfer_format_address(record):
        """ Return a one-line postal address, skipping the parts this record does not have.

        `res.partner` and `res.bank` hold the same pieces under slightly different field names
        (`country_id` against `country`), which is why the country is read defensively rather than
        assumed.

        :param record: A `res.partner` or a `res.bank`.
        :return: The address, empty when the record has none.
        :rtype: str
        """
        if not record:
            return ''
        country = getattr(record, 'country_id', False) or getattr(record, 'country', False)
        locality = ' '.join(part for part in (record.zip, record.city) if part)
        parts = [
            record.street,
            getattr(record, 'street2', ''),
            locality,
            country.name if country else '',
        ]
        return ', '.join(part.strip() for part in parts if part and part.strip())

    def _get_transfer_copy_all(self, rows):
        """ Return the whole card as plain text, for the single "copy all" button.

        Plain text on purpose: this is pasted into an email to an accountant or into a bank's
        notes field, and both mangle anything richer.

        :param list rows: The rows returned by `_get_transfer_details`.
        :return: The text to put on the clipboard.
        :rtype: str
        """
        self.ensure_one()

        lines = [self.company_id.partner_id.name or '']
        lines += [f"{row['label']}: {row['copy']}" for row in rows]
        email = self._get_transfer_provider().transfer_contact_email
        if email:
            lines.append(_("Contact: %s", email))
        return '\n'.join(line for line in lines if line)
