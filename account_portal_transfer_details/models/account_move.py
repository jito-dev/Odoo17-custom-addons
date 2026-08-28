import logging

from odoo import _, fields, models
from odoo.tools.misc import format_date, formatLang

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
            'accent': True,
            'mono': 0,
            # The hero renders the number and the currency code as two elements, so they can be
            # sized independently; the row underneath still copies the plain figure.
            'value_number': formatLang(
                self.env, amount, digits=self.currency_id.decimal_places
            ),
        }, {
            'key': 'holder',
            'label': _("Account holder"),
            'value': company_partner.name,
            'section': _("Who gets paid"),
        }, {
            'key': 'address',
            'label': _("Address"),
            'value': self._transfer_format_address(company_partner),
        }]
        if company_partner.vat:
            rows.append({
                'key': 'vat',
                'label': _("VAT (Tax ID)"),
                'value': company_partner.vat,
                'mono': 0,
            })

        rows += [{
            'key': 'iban',
            'label': _("Account number (IBAN)"),
            'value': bank.acc_number,
            # Grouped for reading, unspaced for pasting: many bank forms refuse the spaces.
            'copy': bank.acc_number.replace(' ', ''),
            'mono': 4,
            'section': _("Where it goes"),
        }, {
            'key': 'bic',
            'label': _("SWIFT / BIC"),
            'value': bank.bank_id.bic,
            'mono': 0,
        }, {
            'key': 'bank_name',
            'label': _("Bank name"),
            'value': bank.bank_id.name,
        }]
        bank_address = self._transfer_format_address(bank.bank_id)
        if bank_address:
            rows.append({
                'key': 'bank_address',
                'label': _("Bank address"),
                'value': bank_address,
            })

        rows.append({
            'key': 'reference',
            'label': _("Payment reference"),
            'value': reference,
            'mono': 0,
            'section': _("What to write in the transfer"),
        })
        if purpose:
            rows.append({
                'key': 'purpose',
                'label': _("Payment purpose"),
                'value': purpose,
            })

        for row in rows:
            row.setdefault('copy', row['value'])
            row.setdefault('mono', -1)
        return rows

    def _get_transfer_card(self):
        """ Return the same rows arranged the way the card reads them.

        The amount is the hero and stands outside the groups; the rest fall into the three
        sections a bank transfer form itself is divided into, so the customer fills their form
        top to bottom without hunting. The grouping lives here rather than in QWeb because a
        template that has to remember where a section starts is a template nobody dares edit.

        Note: `self.ensure_one()`

        :return: `hero`, `groups` and the footer values, or an empty dict when there is no card.
        :rtype: dict
        """
        self.ensure_one()

        rows = self._get_transfer_details()
        if not rows:
            return {}

        hero = next(row for row in rows if row['key'] == 'amount')
        groups, current = [], None
        for row in rows:
            if row is hero:
                continue
            if row.get('section'):
                current = {'title': row['section'], 'rows': []}
                groups.append(current)
            current['rows'].append(row)

        provider = self._get_transfer_provider()
        return {
            'hero': hero,
            'groups': groups,
            'currency': self.currency_id.name,
            'contact_email': provider.transfer_contact_email or self.company_id.email,
            'copy_all': self._get_transfer_copy_all(rows),
            'due': self._get_transfer_due_note(),
            'settled': self._get_transfer_settled_note(),
            'qr': self._get_transfer_qr(provider),
        }

    def _get_transfer_due_note(self):
        """ Return the due date, phrased the way somebody about to pay needs to read it.

        The number on the card answers "how much"; this answers "by when", which is the question
        that decides whether they pay now or file it. An overdue invoice says so plainly rather
        than printing a date the reader has to compare against today themselves.

        Note: `self.ensure_one()`

        :return: `{'text', 'late'}`, or an empty dict when the invoice carries no due date.
        :rtype: dict
        """
        self.ensure_one()

        if not self.invoice_date_due:
            return {}

        days = (self.invoice_date_due - fields.Date.context_today(self)).days
        if days < 0:
            count = abs(days)
            return {
                'text': _("Overdue by %s day", count) if count == 1
                        else _("Overdue by %s days", count),
                'late': True,
            }
        if days == 0:
            return {'text': _("Due today"), 'late': False}
        return {
            'text': _("Due %s", format_date(self.env, self.invoice_date_due)),
            'late': False,
        }

    def _get_transfer_settled_note(self):
        """ Explain the amount when it is not the whole invoice.

        A customer who already paid part of this invoice sees a figure smaller than the one they
        were sent, and has no way to tell whether it is a discount, an error, or their own
        payment. Saying so is also the only acknowledgement they get that the earlier payment
        arrived.

        Note: `self.ensure_one()`

        :return: The sentence, empty when nothing has been paid yet.
        :rtype: str
        """
        self.ensure_one()

        settled = self.amount_total - self.amount_residual
        if self.currency_id.is_zero(settled) or settled < 0:
            return ''
        digits = self.currency_id.decimal_places
        return _(
            "%(paid)s of %(total)s already paid",
            paid=formatLang(self.env, settled, digits=digits),
            total=formatLang(self.env, self.amount_total, digits=digits),
        )

    def _get_transfer_qr(self, provider):
        """ Return the payment QR code for this invoice, when one can be built.

        A scanned QR fills the customer's banking app with the account, the beneficiary, the
        amount and the reference at once — every value on this card, with no chance of a typo.
        It is also the one thing here that cannot be produced for every invoice: the SEPA credit
        transfer standard covers EUR only, so `build_qr_code_base64` returns nothing for a USD
        invoice and the block simply does not appear.

        Note: `self.ensure_one()`

        :param provider: The Wire Transfer provider, which carries the on/off switch.
        :return: The image as a data URI, empty when no method applies.
        :rtype: str
        """
        self.ensure_one()

        if not provider.qr_code or not self.partner_bank_id:
            return ''

        # `silent_errors=True` covers an unsupported currency or an incomplete account, but NOT a
        # failure to render the image: `reportlab` raises outright when its drawing backend is
        # missing (no `rlPyCairo`, no `_rl_renderPM`), and that exception would reach the customer
        # as a 500 on the page they are trying to pay from. A missing QR is a smaller loss than a
        # missing page, every time.
        try:
            return self.partner_bank_id.build_qr_code_base64(
                self.currency_id.round(self.amount_residual),
                self.payment_reference or self.name,
                None,
                self.currency_id,
                self.partner_id,
            ) or ''
        except Exception:  # noqa: BLE001
            _logger.warning(
                "Could not build the payment QR code for %s; the rest of the transfer details "
                "are shown without it. If no QR ever appears, the image backend is probably "
                "missing — `reportlab` needs `rlPyCairo` to draw one.",
                self.display_name, exc_info=True
            )
            return ''

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
