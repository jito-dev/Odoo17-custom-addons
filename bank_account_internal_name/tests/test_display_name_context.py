from lxml import etree

from odoo import Command
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class RecipientBankDisplayNameTest(AccountTestInvoicingCommon):
    """ The internal name is a way to *pick* an account, never a way to show it.

    `bank_by_internal_name` is an opt-in context key, and opting in is per field.
    The web client, though, merges the context of the field being edited into the
    context of the whole `onchange` request, so picking an account by its internal
    name once made the stock "Recipient Bank" read `jito.usd` instead of the IBAN.
    Nothing was written wrong - the right account was selected - but an accountant
    reading the form saw an internal label where the account number belongs.
    """

    @classmethod
    def setUpClass(cls, chart_template_ref=None):
        super().setUpClass(chart_template_ref=chart_template_ref)

        cls.usd = cls.env.ref('base.USD')
        cls.bank = cls.env['res.partner.bank'].create({
            'acc_number': 'LT00 0000 0000 0000 0009',
            'internal_name': 'test.display',
            'partner_id': cls.company_data['company'].partner_id.id,
            'currency_id': cls.usd.id,
            'allow_out_payment': True,
        })
        cls.invoice = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': cls.partner_a.id,
            'currency_id': cls.usd.id,
            'invoice_line_ids': [Command.create({'quantity': 1, 'price_unit': 100.0})],
        })
        cls.invoice.partner_bank_id = cls.bank

    def _account_number_of(self, bank):
        """ How an account reads in a field that did not ask for the internal name. """
        return bank.with_context(display_account_trust=True, bank_by_internal_name=False).display_name

    @property
    def _fields_spec(self):
        """ The two bank fields as the invoice form asks for them. """
        return {
            'partner_bank_id': {
                'fields': {'display_name': {}},
                'context': {'display_account_trust': True, 'bank_by_internal_name': False},
            },
            'recipient_bank_internal_id': {
                'fields': {'display_name': {}},
                'context': {'display_account_trust': True, 'bank_by_internal_name': 1},
            },
        }

    def test_each_field_is_read_under_its_own_context(self):
        """ Read side by side, one shows the account number and the other the label. """
        [values] = self.invoice.web_read(self._fields_spec)

        self.assertEqual(values['partner_bank_id']['display_name'], self._account_number_of(self.bank))
        self.assertEqual(values['recipient_bank_internal_id']['display_name'], 'test.display')

    def test_a_leaked_request_context_does_not_reach_the_recipient_bank(self):
        """ The regression: the key set on the request, not on the field.

        This is what the browser sends while picking an account by internal name.
        The account number must survive it - the field's own context has the last
        word over the request's.
        """
        leaked = self.invoice.with_context(bank_by_internal_name=1)
        [values] = leaked.web_read(self._fields_spec)

        self.assertEqual(values['partner_bank_id']['display_name'], self._account_number_of(self.bank))
        self.assertEqual(values['recipient_bank_internal_id']['display_name'], 'test.display')

    def test_picking_by_internal_name_leaves_the_account_number_in_place(self):
        """ The same, through the `onchange` the form actually performs. """
        other = self.env['res.partner.bank'].create({
            'acc_number': 'LT00 0000 0000 0000 0010',
            'internal_name': 'test.display.other',
            'partner_id': self.company_data['company'].partner_id.id,
            'currency_id': self.usd.id,
            'allow_out_payment': True,
        })

        result = self.invoice.with_context(bank_by_internal_name=1).onchange(
            {
                'id': self.invoice.id,
                'partner_bank_id': self.bank.id,
                'recipient_bank_internal_id': other.id,
            },
            ['recipient_bank_internal_id'],
            self._fields_spec,
        )

        recipient_bank = result['value']['partner_bank_id']
        self.assertEqual(recipient_bank['id'], other.id, "the picked account is the one that lands")
        self.assertEqual(
            recipient_bank['display_name'],
            self._account_number_of(other),
            "the Recipient Bank shows the account number, not the internal label",
        )

    def test_the_form_switches_the_key_off_on_every_recipient_bank(self):
        """ What keeps the two tests above true in the browser.

        The neutralising context lives in the view, so a `partner_bank_id` node
        added by a future Odoo release - or by another module - is caught here
        rather than by an accountant reading `jito.usd` off an invoice.
        """
        arch = etree.fromstring(
            self.env['account.move'].get_view(self.env.ref('account.view_move_form').id, 'form')['arch']
        )
        nodes = arch.xpath("//field[@name='partner_bank_id']")

        self.assertTrue(nodes, "the invoice form has no Recipient Bank field any more")
        for node in nodes:
            self.assertIn(
                "'bank_by_internal_name': False",
                node.get('context') or '',
                "a Recipient Bank field that does not switch the internal-name key off",
            )
