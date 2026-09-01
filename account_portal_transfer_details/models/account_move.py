import logging

from odoo import _, fields, models
from odoo.tools.misc import format_date, formatLang

_logger = logging.getLogger(__name__)

# What a bank actually carries in the free-text purpose of a transfer: SEPA allows 140
# characters of unstructured remittance information, and SWIFT MT103 field :70: is 4 lines
# of 35 - the same number. Past it the text is silently truncated by the bank, or the
# payment is rejected outright.
PURPOSE_MAX_LENGTH = 140


class AccountMove(models.Model):
    _inherit = 'account.move'

    transfer_purpose = fields.Char(
        string="Payment Purpose",
        copy=False,
        help="What this invoice tells the customer to write in the purpose field of their bank. "
             "Left empty, it is built from the products on the invoice - fill it in only when "
             "this invoice needs to say something else.",
    )

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
            # A bank account carrying a currency accepts that currency. Sending USD to an
            # EUR-only account means a conversion at the beneficiary bank's own rate, or a
            # returned transfer days later - and the customer, who was told an exact figure,
            # has no way to see it coming. Odoo picks this account without looking at the
            # currency (`account_move.py::_compute_partner_bank_id`) and rewrites the account's
            # currency behind the invoice whenever its journal is edited
            # (`account_journal.py`), so the invoice and its bank account can drift apart with
            # nobody touching either. An account with no currency is not a mismatch: it means
            # "any currency", which is how Odoo reads an empty currency everywhere else.
            if bank.currency_id and bank.currency_id != self.currency_id:
                missing.append(
                    f'the bank account is in {bank.currency_id.name}, '
                    f'the invoice in {self.currency_id.name}'
                )
        if missing:
            _logger.info(
                "Not showing the bank transfer details on the portal page of %s: %s. Correct "
                "this on the invoice or on the bank account for this invoice to be payable by "
                "transfer.", self.display_name, '; '.join(missing)
            )
            return []

        company_partner = self.company_id.partner_id
        reference = self.payment_reference or self.name
        purpose = self._get_transfer_purpose(provider, reference)
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
            'hero': True,
            # The hero renders the number and the currency code as two elements, so they can be
            # sized independently; the row underneath still copies the plain figure.
            'value_number': formatLang(
                self.env, amount, digits=self.currency_id.decimal_places
            ),
        }, {
            'key': 'currency',
            'label': _("Currency"),
            # A field of its own rather than a suffix on the amount: a transfer form asks for the
            # currency separately, and the amount is copied as bare digits precisely because a
            # bank rejects the code there — which left the currency in nothing the customer could
            # actually copy, the copy-all text included.
            'value': self.currency_id.name,
            'mono': 0,
            'hero': True,
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

    def _get_transfer_purpose(self, provider, reference):
        """ Return the line the customer is told to write in the purpose field of their bank.

        The template on the provider is the *format*; what the invoice is actually for comes
        from the invoice, through `{services}`. A template without the placeholder is left
        exactly as it was, so an installation that phrased its own line keeps it.

        Only the services are shortened when the whole thing does not fit. Cutting the line as
        one string would eat the reference off the end, and a transfer that arrives without a
        reference cannot be matched to an invoice by anyone.

        Note: `self.ensure_one()`

        :param provider: The Wire Transfer `payment.provider`.
        :param str reference: The payment reference already resolved by the caller.
        :return: The purpose, empty when the provider has no template at all.
        :rtype: str
        """
        self.ensure_one()

        purpose = (provider.transfer_purpose_template or '').replace('{reference}', reference)
        placeholders = purpose.count('{services}')
        if placeholders:
            # Measured with the placeholder still in place and its own length taken back off:
            # measuring the string with it removed collapses the space it stood between, and the
            # room comes out one character too generous — which is exactly one character off the
            # end of the reference.
            fixed = len(self._transfer_clean_text(purpose)) - len('{services}') * placeholders
            room = (PURPOSE_MAX_LENGTH - fixed) // placeholders
            purpose = purpose.replace(
                '{services}', self._transfer_shorten(self._get_transfer_services(), room)
            )
        # With no services to name, the placeholder leaves the separator it was written next to
        # behind ("- Invoice INV/2026/00341"); stripping it is what keeps the worst case tidy.
        return self._transfer_clean_text(purpose).strip(' -\u2013\u2014,;:')[:PURPOSE_MAX_LENGTH]

    def _get_transfer_services(self):
        """ Return what this invoice is for, phrased for a bank rather than for the catalogue.

        First whatever the invoice says itself, then the products on it, and only then the line
        descriptions - each step is a place someone can correct the one below it without editing
        every invoice.

        Line descriptions are read one line deep on purpose: a line billed from timesheets
        carries the period and the hours underneath its title, and none of that means anything
        in a bank's purpose field.

        Note: `self.ensure_one()`

        :return: The services, empty when the invoice has nothing to name them with.
        :rtype: str
        """
        self.ensure_one()

        if self.transfer_purpose:
            return self._transfer_clean_text(self.transfer_purpose)

        names = []
        for line in self.invoice_line_ids.filtered(lambda line: line.display_type == 'product'):
            name = ''
            if line.product_id:
                name = line.product_id.transfer_purpose_name or line.product_id.name
            if not name:
                name = (line.name or '').split('\n')[0]
            name = self._transfer_clean_text(name)
            # Ten lines of the same service must read as one thing, not ten.
            if name and name not in names:
                names.append(name)
        return ', '.join(names)

    @staticmethod
    def _transfer_clean_text(text):
        """ Return the text as the single line a bank form accepts.

        :param str text: Any description, possibly multi-line.
        :return: The same words, whitespace collapsed.
        :rtype: str
        """
        return ' '.join((text or '').split())

    @staticmethod
    def _transfer_shorten(text, limit):
        """ Return the text cut to `limit` characters, saying that it was cut.

        The ellipsis is the three ASCII dots and not `…`: the SEPA character set does not
        contain it, and a bank that validates strictly refuses the whole field over it.

        :param str text: The text to fit.
        :param int limit: The characters available for it.
        :return: The text, cut when it has to be.
        :rtype: str
        """
        if limit <= 0:
            return ''
        if len(text) <= limit:
            return text
        if limit <= 3:
            return text[:limit]
        return text[:limit - 3].rstrip(' ,;') + '...'

    def _get_transfer_card(self):
        """ Return the same rows arranged the way the card reads them.

        The amount and the currency are the hero and stand outside the groups; the rest fall into
        the three sections a bank transfer form itself is divided into, so the customer fills their
        form top to bottom without hunting. The grouping lives here rather than in QWeb because a
        template that has to remember where a section starts is a template nobody dares edit.

        Note: `self.ensure_one()`

        :return: `hero`, `groups` and the footer values, or an empty dict when there is no card.
        :rtype: dict
        """
        self.ensure_one()

        rows = self._get_transfer_details()
        if not rows:
            return {}

        # `hero` is the figure printed large; `hero_rows` are the copyable rows under it. A row
        # that is neither must carry a section, or it has nowhere to go.
        hero = next(row for row in rows if row['key'] == 'amount')
        hero_rows = [row for row in rows if row.get('hero')]
        groups, current = [], None
        for row in rows:
            if row.get('hero'):
                continue
            if row.get('section'):
                current = {'title': row['section'], 'rows': []}
                groups.append(current)
            current['rows'].append(row)

        provider = self._get_transfer_provider()
        return {
            'hero': hero,
            'hero_rows': hero_rows,
            'groups': groups,
            'currency': self.currency_id.name,
            'contact_email': provider.transfer_contact_email or self.company_id.email,
            'copy_all': self._get_transfer_copy_all(rows),
            'due': self._get_transfer_due_note(),
            'settled': self._get_transfer_settled_note(),
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
