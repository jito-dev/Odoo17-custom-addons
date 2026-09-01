from datetime import timedelta

from odoo import fields
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
            'transfer_purpose_template': "{services} - Invoice {reference}",
        })
        cls.product_dev = cls.env['product.product'].create({
            'name': "Senior Developer, hourly",
            'type': 'service',
        })
        cls.product_design = cls.env['product.product'].create({
            'name': "UI/UX Design",
            'type': 'service',
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

    def _invoice_for(self, lines, purpose=None):
        """ An invoice whose lines are (product, description) pairs, either of which may be None. """
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_a.id,
            'transfer_purpose': purpose or False,
            'invoice_line_ids': [
                (0, 0, {
                    'product_id': product.id if product else False,
                    'name': 'x' if name is None else name,
                    'quantity': 1,
                    'price_unit': 100.0,
                })
                for product, name in lines
            ],
        })
        invoice.partner_bank_id = self.account
        invoice.action_post()
        return invoice

    def _purpose(self, invoice):
        return self._row(invoice._get_transfer_details(), 'purpose')['value']

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

    def test_the_currency_is_a_field_of_its_own(self):
        invoice = self._invoice()
        rows = invoice._get_transfer_details()
        currency = self._row(rows, 'currency')

        self.assertTrue(currency, (
            "A transfer form asks for the currency in its own box. The amount is copied as bare "
            "digits precisely because a bank rejects a currency code there, so without this row "
            "the currency is in nothing the customer can copy - and the copy-all text pastes an "
            "amount with no currency at all."
        ))
        self.assertEqual(currency['value'], invoice.currency_id.name, msg=(
            "The currency must be the invoice's own, as its ISO code: '$' is three different "
            "currencies and this value is retyped into an international transfer.\n"
            f"    expected: {invoice.currency_id.name}\n    actual:   {currency['value']}"
        ))
        self.assertEqual(currency['copy'], invoice.currency_id.name, (
            "What is copied must be the bare code - a currency box takes 'USD', nothing else."
        ))

    def test_the_currency_stands_with_the_amount(self):
        card = self._invoice()._get_transfer_card()
        keys = [row['key'] for row in card['hero_rows']]

        self.assertEqual(keys, ['amount', 'currency'], msg=(
            "The currency belongs next to the amount, which is where a bank transfer form puts "
            "it, so the customer fills their form top to bottom without hunting.\n"
            f"    got: {keys}"
        ))
        grouped = [row['key'] for group in card['groups'] for row in group['rows']]
        self.assertNotIn('currency', grouped, (
            "A hero row must not also appear inside a section - the customer would see the same "
            "value twice and have to wonder which one is meant."
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

    # === What the invoice is for === #

    def test_the_purpose_names_the_products_on_the_invoice(self):
        purpose = self._purpose(self._invoice_for([(self.product_dev, None)]))
        self.assertIn("Senior Developer, hourly", purpose, msg=(
            "'{services}' must be replaced with what the invoice is actually for. A fixed line "
            "means every customer is told they are paying for the same thing, which is wrong on "
            "every invoice but one.\n    purpose: " + purpose
        ))

    def test_the_product_can_be_named_differently_for_the_bank(self):
        self.product_dev.transfer_purpose_name = "IT consulting services"
        purpose = self._purpose(self._invoice_for([(self.product_dev, None)]))
        self.assertIn("IT consulting services", purpose, msg=(
            "A product's Payment Purpose Name must win over its catalogue name. The catalogue is "
            "written for the salesperson; this line is read by a compliance officer at a bank."
        ))
        self.assertNotIn("Senior Developer", purpose, msg=(
            "...and the catalogue name must then be gone, not appended. Two names for one "
            "service reads as two services."
        ))

    def test_the_invoice_overrides_everything(self):
        self.product_dev.transfer_purpose_name = "IT consulting services"
        purpose = self._purpose(
            self._invoice_for([(self.product_dev, None)], purpose="Retainer, Q3 2026")
        )
        self.assertIn("Retainer, Q3 2026", purpose, msg=(
            "The Payment Purpose on the invoice must beat both the product and the products' "
            "names. It exists for the invoice the general rule gets wrong, and a rule nobody can "
            "override is a rule that gets worked around by editing the provider for everyone."
        ))
        self.assertNotIn("consulting", purpose, msg=(
            "The override replaces the services; it does not join them."
        ))

    def test_several_products_are_listed_once_each(self):
        purpose = self._purpose(self._invoice_for([
            (self.product_dev, None),
            (self.product_design, None),
            (self.product_dev, None),
        ]))
        self.assertIn("Senior Developer, hourly", purpose)
        self.assertIn("UI/UX Design", purpose, msg=(
            "Every distinct service on the invoice must be named — a customer paying one transfer "
            "for two services should see both."
        ))
        self.assertEqual(purpose.count("Senior Developer"), 1, msg=(
            "...and each of them only once. Ten lines of the same service are one thing to a "
            f"bank, not ten.\n    purpose: {purpose}"
        ))

    def test_a_line_without_a_product_falls_back_to_its_first_line(self):
        purpose = self._purpose(self._invoice_for([
            (None, "Development services\nSprint 12, 118.5 h at 45.00 USD"),
        ]))
        self.assertIn("Development services", purpose, msg=(
            "An invoice line typed by hand still has to say something. Falling through to a blank "
            "purpose would be a regression against the fixed text this replaced."
        ))
        self.assertNotIn("Sprint 12", purpose, msg=(
            "Only the first line of the description belongs in a bank's purpose field. What a "
            "timesheet line carries underneath — period, hours, rate — is noise there, and it is "
            "what pushes the line past the length a transfer accepts."
        ))

    # === What a bank will actually accept === #

    def test_the_purpose_fits_what_a_transfer_carries(self):
        self.product_dev.transfer_purpose_name = "Bespoke software engineering, " + "a" * 200
        invoice = self._invoice_for([(self.product_dev, None)])
        purpose = self._purpose(invoice)

        self.assertLessEqual(len(purpose), 140, msg=(
            "SEPA carries 140 characters of remittance information and SWIFT MT103 field 70 the "
            f"same. Longer, and the bank truncates it or refuses the payment.\n    length: "
            f"{len(purpose)}\n    purpose: {purpose}"
        ))
        self.assertIn(invoice.payment_reference, purpose, msg=(
            "The reference must survive the cut. Only the services may be shortened: a transfer "
            "that arrives without a reference cannot be matched to an invoice by anybody, which "
            "is the one failure this whole card exists to prevent."
        ))
        self.assertIn('...', purpose, msg=(
            "A shortened description must show that it was shortened, or the customer copies a "
            "sentence that stops mid-word and assumes it is what we meant."
        ))

    def test_the_purpose_is_always_one_line(self):
        purpose = self._purpose(self._invoice_for([
            (None, "Development services\nSprint 12"),
            (None, "Support   retainer"),
        ]))
        self.assertNotIn('\n', purpose, msg=(
            "A bank purpose field is one line. A newline in it is either dropped silently or "
            "splits the value across fields nobody checks."
        ))
        self.assertNotIn('  ', purpose, msg=(
            "Doubled spaces come from concatenating descriptions and look like a bug to the "
            "customer retyping them."
        ))

    def test_an_invoice_with_nothing_to_name_still_reads_as_a_sentence(self):
        # No product and no description: nothing on this invoice names a service, so
        # `{services}` resolves to nothing at all.
        invoice = self._invoice_for([(None, '')])
        purpose = self._purpose(invoice)

        self.assertFalse(purpose.startswith('-'), msg=(
            "With no services to name, the separator the placeholder sat next to must go with it. "
            f"'- Invoice INV/...' reads as a mistake on a page asking for money.\n    purpose: "
            f"{purpose}"
        ))
        self.assertIn(invoice.payment_reference, purpose, msg=(
            "The reference must still be there. An empty purpose row is the one outcome worse "
            "than the fixed text this replaced."
        ))

    def test_a_template_without_the_placeholder_is_left_alone(self):
        self.provider.transfer_purpose_template = "Invoice {reference}"
        purpose = self._purpose(self._invoice_for([(self.product_dev, None)]))
        self.assertNotIn("Senior Developer", purpose, msg=(
            "A template that never asked for the services must not get them. Someone who phrased "
            "their own line meant that line, and the upgrade must not rewrite it for them."
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

    @mute_logger(_MODEL_LOGGER)
    def test_nothing_is_shown_when_the_account_is_in_another_currency(self):
        invoice = self._invoice()
        self.account.currency_id = self.currency_data['currency']
        self.assertNotEqual(self.account.currency_id, invoice.currency_id, msg=(
            "Fixture check: this test is only meaningful while the account and the invoice "
            "disagree about the currency."
        ))
        self.assertFalse(invoice._get_transfer_details(), (
            "Money sent in the invoice currency to an account that only holds another one is "
            "converted at the beneficiary bank's own rate or returned days later, and the "
            "customer was told an exact figure. Odoo picks the Recipient Bank without looking "
            "at the currency, and rewrites the account currency whenever its journal is edited, "
            "so this drifts apart with nobody touching the invoice. No card is the safe answer."
        ))

    def test_an_account_in_the_invoice_currency_is_shown(self):
        invoice = self._invoice()
        self.account.currency_id = invoice.currency_id
        self.assertTrue(invoice._get_transfer_details(), (
            "An account explicitly in the currency of the invoice is the case the guard exists "
            "to protect, not to block."
        ))

    def test_an_account_without_a_currency_is_shown(self):
        invoice = self._invoice()
        self.account.currency_id = False
        self.assertTrue(invoice._get_transfer_details(), (
            "An empty currency on a bank account means \"any currency\" - that is how Odoo reads "
            "it everywhere else, provider currencies included. Treating it as a mismatch would "
            "hide the card on nearly every database, since the field is rarely filled in."
        ))

    # === Context around the amount === #

    def test_an_overdue_invoice_says_so(self):
        invoice = self._invoice()
        invoice.invoice_date_due = fields.Date.context_today(invoice) - timedelta(days=3)
        due = invoice._get_transfer_card()['due']
        self.assertTrue(due['late'], (
            "An invoice past its due date must be flagged as late. A bare date leaves the reader "
            "to compare it against today themselves, which is exactly the step people skip."
        ))
        self.assertIn('3', due['text'], msg=(
            f"The wording must carry how late it is, not just that it is late.\n"
            f"    got: {due['text']}"
        ))

    def test_a_future_due_date_is_a_date_not_a_warning(self):
        invoice = self._invoice()
        invoice.invoice_date_due = fields.Date.context_today(invoice) + timedelta(days=10)
        due = invoice._get_transfer_card()['due']
        self.assertFalse(due['late'], (
            "An invoice that is not yet due must not be dressed as overdue — crying wolf on a "
            "normal invoice teaches the customer to ignore the line that matters."
        ))

    def test_no_due_date_produces_no_line(self):
        invoice = self._invoice()
        invoice.invoice_date_due = False
        self.assertFalse(invoice._get_transfer_card()['due'], (
            "With no due date there is nothing truthful to say, and inventing one is worse than "
            "the silence."
        ))

    def test_a_partial_payment_is_explained(self):
        invoice = self._invoice(price=1000.0)
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids
        ).create({'amount': 400.0})._create_payments()

        settled = invoice._get_transfer_card()['settled']
        self.assertTrue(settled, (
            "A customer who already paid part of this invoice sees a figure smaller than the one "
            "they were sent. Without a word of explanation they cannot tell a discount from an "
            "error from their own payment."
        ))
        self.assertIn('400', settled, msg=f"    got: {settled}")
        self.assertIn('1,000', settled, msg=f"    got: {settled}")

    def test_an_untouched_invoice_says_nothing_about_payments(self):
        self.assertFalse(self._invoice()._get_transfer_card()['settled'], (
            "With nothing paid yet the line has no content, and '0.00 of 100.00 already paid' is "
            "noise pretending to be information."
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

    def test_copy_all_carries_the_services(self):
        invoice = self._invoice_for([(self.product_dev, None)])
        text = invoice._get_transfer_copy_all(invoice._get_transfer_details())
        self.assertIn("Senior Developer, hourly", text, msg=(
            "The copy-all button is how most customers move these values into their bank, so the "
            "purpose it pastes must be the same one shown on the card. A row that reads correctly "
            "on screen and pastes the old fixed line is worse than no button."
        ))
