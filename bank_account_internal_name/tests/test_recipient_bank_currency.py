from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class RecipientBankCurrencyTest(AccountTestInvoicingCommon):
    """ Which of the company's bank accounts an invoice tells the customer to pay into.

    Stock Odoo picks the first one it finds and never looks at the currency, which is
    how a USD invoice goes out printing a EUR IBAN — or an account left over from a
    setup session. Every test here states the rule it protects and what it costs when
    it breaks, because the failure is silent: nothing errors, the invoice is simply
    sent with the wrong bank details.
    """

    @classmethod
    def setUpClass(cls, chart_template_ref=None):
        super().setUpClass(chart_template_ref=chart_template_ref)

        cls.usd = cls.env.ref('base.USD')
        cls.eur = cls.env.ref('base.EUR')
        cls.company_partner = cls.company_data['company'].partner_id

        # The company starts with no bank account of its own; everything below is
        # created here so the test does not depend on the chart template's fixtures.
        Bank = cls.env['res.partner.bank']
        cls.bank_usd = Bank.create({
            'acc_number': 'LT00 0000 0000 0000 0001',
            'internal_name': 'test.usd',
            'partner_id': cls.company_partner.id,
            'currency_id': cls.usd.id,
            'allow_out_payment': True,
            'sequence': 1,
        })
        cls.bank_usd_second = Bank.create({
            'acc_number': 'LT00 0000 0000 0000 0002',
            'internal_name': 'test.usd.other',
            'partner_id': cls.company_partner.id,
            'currency_id': cls.usd.id,
            'allow_out_payment': True,
            'sequence': 5,
        })
        cls.bank_eur = Bank.create({
            'acc_number': 'LT00 0000 0000 0000 0003',
            'internal_name': 'test.eur',
            'partner_id': cls.company_partner.id,
            'currency_id': cls.eur.id,
            'allow_out_payment': True,
            'sequence': 1,
        })
        # No currency, lowest sequence: the shape of the `test-to-delete` account that
        # every invoice up to INV/2026/00332 was printed with.
        cls.bank_no_currency = Bank.create({
            'acc_number': 'leftover-from-setup',
            'partner_id': cls.company_partner.id,
            'allow_out_payment': True,
            'sequence': 0,
        })

    def _invoice(self, currency):
        return self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_a.id,
            'currency_id': currency.id,
            'invoice_line_ids': [(0, 0, {'name': 'x', 'quantity': 1, 'price_unit': 100})],
        })

    def _assert_bank(self, invoice, expected, why):
        self.assertEqual(
            invoice.partner_bank_id, expected,
            f"{why}\n"
            f"    invoice currency: {invoice.currency_id.name}\n"
            f"    expected:         {expected.internal_name or expected.acc_number} "
            f"(id={expected.id}, {expected.currency_id.name or 'no currency'})\n"
            f"    actual:           "
            f"{invoice.partner_bank_id.internal_name or invoice.partner_bank_id.acc_number or '(empty)'} "
            f"(id={invoice.partner_bank_id.id}, "
            f"{invoice.partner_bank_id.currency_id.name or 'no currency'})"
        )

    # === The rule itself === #

    def test_default_follows_the_invoice_currency(self):
        self._assert_bank(
            self._invoice(self.usd), self.bank_usd,
            "A USD invoice must default to the USD account. Without this the customer "
            "is told to pay a EUR IBAN, and the money either bounces or arrives on an "
            "account nobody is reconciling.",
        )
        self._assert_bank(
            self._invoice(self.eur), self.bank_eur,
            "A EUR invoice must default to the EUR account — the same rule, the other "
            "way round; a test that only covers one currency would pass on a hardcoded "
            "answer.",
        )

    def test_sequence_breaks_the_tie_between_two_accounts_of_one_currency(self):
        self._assert_bank(
            self._invoice(self.usd), self.bank_usd,
            "With two USD accounts the one with the lower `sequence` must win. That is "
            "what makes the default a configuration the accountant drags in the list, "
            "rather than an accident of which account was created first.",
        )
        self.bank_usd.sequence = 9  # now the other one is first
        self._assert_bank(
            self._invoice(self.usd), self.bank_usd_second,
            "Reordering the accounts must change the default. If it does not, the "
            "handle in the bank accounts list is decoration and the choice is stuck "
            "with creation order.",
        )

    def test_account_without_a_currency_is_never_the_default(self):
        invoice = self._invoice(self.usd)
        self.assertNotEqual(
            invoice.partner_bank_id, self.bank_no_currency,
            "An account with no currency must never win over one that matches. It has "
            "the lowest sequence here on purpose: this is the exact shape of the "
            "leftover account that got printed on 302 invoices.",
        )

    def test_currency_without_an_account_keeps_the_stock_default(self):
        gbp = self.env.ref('base.GBP')
        gbp.active = True
        invoice = self._invoice(gbp)
        self.assertTrue(
            invoice.partner_bank_id,
            "A currency with no account of its own must still get a bank — the stock "
            "result stands. Leaving the field empty would send an invoice with no "
            "payment details at all, which is worse than an imperfect account.",
        )

    # === What the accountant does next === #

    def test_manual_choice_is_kept(self):
        invoice = self._invoice(self.usd)
        invoice.partner_bank_id = self.bank_eur
        self._assert_bank(
            invoice, self.bank_eur,
            "A hand-picked account must survive, including one in another currency. "
            "The rule is a default, not a constraint: the accountant knows about cases "
            "the currency cannot express.",
        )

    def test_changing_the_currency_re_picks_the_account(self):
        invoice = self._invoice(self.usd)
        invoice.partner_bank_id = self.bank_usd_second
        invoice.currency_id = self.eur
        self._assert_bank(
            invoice, self.bank_eur,
            "Changing the currency must re-pick the account, overwriting a manual "
            "choice. This is the agreed trade-off: an account left over from the "
            "previous currency is a worse default than one that can be picked again.",
        )

    def test_internal_name_field_mirrors_the_default(self):
        invoice = self._invoice(self.usd)
        self.assertEqual(
            invoice.recipient_bank_internal_id, invoice.partner_bank_id,
            "The 'Recipient Bank Internal Name' helper must show the same account as "
            "'Recipient Bank'. Two fields pointing at different accounts is worse than "
            "one field, because each looks authoritative on its own.",
        )
