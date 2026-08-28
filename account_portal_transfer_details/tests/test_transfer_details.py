from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged
from odoo.tools import mute_logger

_MODEL_LOGGER = 'odoo.addons.account_portal_transfer_details.models.account_move'


@tagged('post_install', '-at_install')
class TransferDetailsTest(AccountTestInvoicingCommon):
    """ What the customer is told to type into their bank.

    Every failure here is silent and expensive: nothing errors, the invoice simply carries wrong
    or incomplete transfer instructions, and the money goes to the wrong place or nowhere.
    """

    @classmethod
    def setUpClass(cls, chart_template_ref=None):
        super().setUpClass(chart_template_ref=chart_template_ref)

        cls.company = cls.company_data['company']
        cls.company.partner_id.write({
            'name': "Test Beneficiary Ltd",
            'vat': 'CY10440090J',
            'street': "Arch. Makariou III Avenue 195",
            'city': "Limassol",
            'zip': '3030',
        })
        cls.bank = cls.env['res.bank'].create({
            'name': "Revolut Bank UAB",
            'bic': 'REVOLT21',
            'street': "Konstitucijos ave. 21B",
            'city': "Vilnius",
            'zip': '08130',
        })
        cls.account = cls.env['res.partner.bank'].create({
            'acc_number': 'LT74 3250 0463 8592 8454',
            'partner_id': cls.company.partner_id.id,
            'bank_id': cls.bank.id,
            'allow_out_payment': True,
        })
        cls.provider = cls.env['payment.provider'].create({
            'name': "Wire Transfer",
            'code': 'custom',
            'custom_mode': 'wire_transfer',
            'state': 'test',
            'company_id': cls.company.id,
            'transfer_contact_email': 'payments@example.com',
            'transfer_purpose_template': "Software development services - Invoice {reference}",
        })

    def _invoice(self, price=100.0):
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_a.id,
            'invoice_line_ids': [(0, 0, {'name': 'x', 'quantity': 1, 'price_unit': price})],
        })
        invoice.partner_bank_id = self.account
        invoice.action_post()
        return invoice

    def _row(self, rows, key):
        return next((row for row in rows if row['key'] == key), None)

    # === The values themselves === #

    def test_the_card_is_built_from_the_invoice(self):
        rows = self._invoice()._get_transfer_details()
        self.assertTrue(rows, "The card must be built when the invoice has a complete bank account.")
        for key, expected in (
            ('holder', "Test Beneficiary Ltd"),
            ('vat', 'CY10440090J'),
            ('iban', 'LT74 3250 0463 8592 8454'),
            ('bic', 'REVOLT21'),
            ('bank_name', "Revolut Bank UAB"),
        ):
            self.assertEqual(self._row(rows, key)['value'], expected, msg=(
                f"The row '{key}' must come from the invoice's own bank account and company. A "
                f"wrong value here is a transfer sent to the wrong beneficiary.\n"
                f"    expected: {expected}\n"
                f"    actual:   {self._row(rows, key)['value']}"
            ))

    def test_the_amount_is_what_is_still_due(self):
        invoice = self._invoice(price=1000.0)
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids
        ).create({'amount': 400.0})._create_payments()

        amount = self._row(invoice._get_transfer_details(), 'amount')
        self.assertIn('600', amount['copy'], msg=(
            "After a partial payment the card must show what is LEFT to pay, not the invoice "
            "total. Showing the total makes the customer transfer the whole amount a second "
            "time.\n"
            f"    invoice total: 1000, already paid: 400\n"
            f"    shown: {amount['value']} / copied: {amount['copy']}"
        ))

    def test_what_is_copied_is_what_a_bank_accepts(self):
        rows = self._invoice(price=1234.5)._get_transfer_details()
        iban, amount = self._row(rows, 'iban'), self._row(rows, 'amount')

        self.assertEqual(iban['copy'], 'LT743250046385928454', msg=(
            "The IBAN must be copied without spaces. Many bank forms refuse a grouped IBAN, and "
            "the customer cannot tell that the spaces are the problem.\n"
            f"    displayed: {iban['value']}\n    copied:    {iban['copy']}"
        ))
        self.assertEqual(iban['value'], 'LT74 3250 0463 8592 8454', (
            "The IBAN must still be DISPLAYED grouped — that is what makes it checkable by eye."
        ))
        self.assertNotIn(self.company.currency_id.name, amount['copy'], msg=(
            "The amount must be copied as bare digits. An amount field rejects a currency code, "
            f"and rejects the grouping separator with it.\n    copied: {amount['copy']}"
        ))

    def test_the_purpose_carries_the_invoice_reference(self):
        invoice = self._invoice()
        purpose = self._row(invoice._get_transfer_details(), 'purpose')
        self.assertIn(invoice.payment_reference, purpose['value'], msg=(
            "'{reference}' in the configured purpose must be replaced with the payment reference. "
            "A purpose without it leaves the accountant guessing which invoice the money is for."
        ))

    # === When the details are not complete === #

    @mute_logger(_MODEL_LOGGER)
    def test_nothing_is_shown_without_a_recipient_bank(self):
        invoice = self._invoice()
        invoice.partner_bank_id = False
        self.assertFalse(invoice._get_transfer_details(), (
            "With no Recipient Bank there is no account to pay into, so the card must not appear "
            "at all. A card with a blank IBAN invites a transfer that cannot arrive."
        ))

    @mute_logger(_MODEL_LOGGER)
    def test_nothing_is_shown_without_a_bic(self):
        invoice = self._invoice()
        self.bank.bic = False
        self.assertFalse(invoice._get_transfer_details(), (
            "An international transfer without a BIC is refused by the correspondent bank or sits "
            "in limbo for weeks. Showing the rest of the card with a dash where the BIC belongs "
            "hides a missing setting behind something that looks deliberate."
        ))

    def test_nothing_is_shown_when_transfers_are_not_offered(self):
        invoice = self._invoice()
        self.provider.state = 'disabled'
        self.assertFalse(invoice._get_transfer_details(), (
            "The card is the Wire Transfer provider's page presence. With the provider disabled "
            "the company is not accepting transfers, and the portal must not say otherwise."
        ))

    def test_a_currency_the_provider_excludes_is_not_offered(self):
        invoice = self._invoice()
        other = self.env.ref('base.CHF')
        other.active = True
        self.provider.available_currency_ids = [(6, 0, other.ids)]
        self.assertFalse(invoice._get_transfer_details(), (
            "A provider restricted to other currencies must not produce a card for this invoice — "
            "that is the same rule the portal applies to every other payment method."
        ))

    # === The copy-all text === #

    def test_copy_all_is_plain_text_with_every_row(self):
        invoice = self._invoice()
        rows = invoice._get_transfer_details()
        text = invoice._get_transfer_copy_all(rows)

        self.assertNotIn('<', text, (
            "Copy-all is pasted into an email or a bank's notes field; both mangle markup."
        ))
        for row in rows:
            self.assertIn(row['copy'], text, msg=(
                f"Every row must appear in the copy-all text — a customer who used the button "
                f"should not have to come back for one missing value.\n    missing: {row['label']}"
            ))
        self.assertIn('payments@example.com', text, (
            "The contact address belongs in the copy-all text: it is what the recipient of that "
            "paste replies to."
        ))
