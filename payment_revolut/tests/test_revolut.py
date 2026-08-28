from unittest.mock import call, patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.payment_revolut import const
from odoo.addons.payment_revolut.controllers.main import RevolutController
from odoo.addons.payment_revolut.tests.common import REQUEST_PATH, RevolutCommon


@tagged('post_install', '-at_install')
class RevolutTest(RevolutCommon):
    """ The order sent to Revolut when the customer clicks 'Pay now', and the redirection.

    What comes back afterwards lives in `test_revolut_states.py`.
    """

    # === The order request === #

    def test_order_payload_values(self):
        """ The order is sent in minor units and carries the reference on every channel. """
        tx = self._create_transaction(flow='redirect')

        payload = tx._revolut_prepare_order_payload()

        self.assertPayloadValue(payload, 'amount', 111111, why=(
            "The amount must be sent in minor units (1111.11 EUR is 111111 cents). Sent in major "
            "units, the customer is charged a hundredth of what they owe."
        ))
        self.assertPayloadValue(payload, 'currency', 'EUR', why=(
            "The order must be created in the currency of the transaction."
        ))
        self.assertPayloadValue(payload, 'capture_mode', 'automatic', why=(
            "Without manual capture configured, Revolut must capture the payment itself. Left on "
            "manual, the money stays merely reserved and is released after a few days."
        ))
        self.assertPayloadValue(payload, 'description', tx.reference, why=(
            "The description is what the customer sees on the payment page and on their statement."
        ))
        self.assertEqual(
            payload.get('merchant_order_data', {}).get('reference'), tx.reference,
            msg=(
                "`merchant_order_data.reference` is what Revolut echoes in the merchant portal and "
                "in the payout statement; without it, a payout cannot be traced back to an order."
            ),
        )
        self.assertEqual(
            payload.get('metadata', {}).get('odoo_reference'), tx.reference,
            msg=(
                "`metadata.odoo_reference` comes back on the order itself and is the last resort "
                "for matching a payment to its transaction."
            ),
        )
        self.assertIn(
            RevolutController._return_url, payload.get('redirect_url', ''),
            msg=(
                "The customer must be sent back to this module's return route.\n"
                f"    redirect_url: {payload.get('redirect_url')}"
            ),
        )
        self.assertIn(
            'reference=', payload.get('redirect_url', ''),
            msg=(
                "The reference must travel in the return URL: Revolut redirects the customer back "
                "without any hint of which order they just paid.\n"
                f"    redirect_url: {payload.get('redirect_url')}"
            ),
        )

    def test_order_payload_sets_an_expiry(self):
        """ An order nobody pays must die on its own, or the invoice stays locked. """
        tx = self._create_transaction(flow='redirect')

        self.assertPayloadValue(
            tx._revolut_prepare_order_payload(), 'expire_pending_after',
            const.ORDER_EXPIRE_PENDING_AFTER, why=(
                "The order must carry an expiry window. Without it, Revolut keeps an unpaid order "
                "pending forever; Odoo hides the portal 'Pay now' button while a transaction is "
                "pending, so a customer who closes the checkout page can never pay that invoice "
                "online again. The window can only be set when the order is created."
            ),
        )

    def test_order_payload_asks_for_manual_capture(self):
        """ The capture mode follows the provider configuration. """
        self.provider.capture_manually = True
        tx = self._create_transaction(flow='redirect')

        self.assertPayloadValue(
            tx._revolut_prepare_order_payload(), 'capture_mode', 'manual', why=(
                "With manual capture configured, the order must only authorise the payment. "
                "Capturing automatically charges customers before anyone approved the order."
            ),
        )

    def test_order_payload_includes_the_customer_when_the_email_is_known(self):
        """ Revolut shows the customer on the checkout page and emails them the receipt. """
        tx = self._create_transaction(flow='redirect')

        customer = tx._revolut_prepare_order_payload().get('customer', {})

        self.assertEqual(
            customer.get('email'), self.partner.email,
            msg=(
                "The customer's email must be passed on so that Revolut can send them the receipt."
                f"\n    customer block sent: {customer}"
            ),
        )
        self.assertEqual(
            customer.get('full_name'), self.partner.name,
            msg=f"The customer's name is shown on the payment page.\n    customer block: {customer}",
        )

    def test_order_payload_omits_the_customer_without_an_email(self):
        """ Revolut refuses a customer block that has no email, so it is left out entirely. """
        anonymous_partner = self.env['res.partner'].create({'name': "Anonymous Buyer"})
        tx = self._create_transaction(flow='redirect', partner_id=anonymous_partner.id)

        payload = tx._revolut_prepare_order_payload()

        self.assertNotIn(
            'customer', payload,
            msg=(
                "Without an email, the whole customer block must be omitted. Sent empty, Revolut "
                "rejects the order and the customer cannot pay at all.\n"
                f"    customer block sent: {payload.get('customer')}"
            ),
        )

    def test_zero_decimal_currency_is_not_scaled(self):
        """ A yen is already a minor unit; multiplying it by 100 would charge 100 times too much. """
        tx = self._create_transaction(
            flow='redirect', currency_id=self._prepare_currency('JPY').id, amount=1500.0
        )

        self.assertPayloadValue(tx._revolut_prepare_order_payload(), 'amount', 1500, why=(
            "JPY has no minor unit, so 1500 JPY must be sent as 1500. Scaled like a decimal "
            "currency it becomes 150000 and the customer is charged a hundred times the price."
        ))

    def test_local_base_url_is_refused_before_reaching_the_api(self):
        """ Revolut rejects the whole order when the return URL is local; say so up front. """
        tx = self._create_transaction(flow='redirect')
        for base_url in ('http://localhost:8069', 'http://192.168.1.10:8069', 'http://[::1]:8069'):
            with self.subTest(base_url=base_url):
                self.env['ir.config_parameter'].sudo().set_param('web.base.url', base_url)
                with self.assertRaises(
                    ValidationError,
                    msg=(
                        f"A base URL of {base_url} must be refused before the order is sent. "
                        f"Revolut rejects the whole order — not just the redirection — for a local "
                        f"return URL, and answers with a bare 'Bad Request' that says nothing "
                        f"about `web.base.url`."
                    ),
                ):
                    tx._revolut_prepare_order_payload()

    # === The redirection to the checkout page === #

    def test_redirect_uses_the_checkout_url_and_stores_the_order_id(self):
        """ The customer is sent to the checkout URL, and the order id is kept for later. """
        tx = self._create_transaction(flow='redirect')

        with patch(REQUEST_PATH, return_value=self.order_data) as api:
            rendering_values = tx._get_specific_rendering_values(None)

        self.assertApiCalls(api, [call('orders', payload=tx._revolut_prepare_order_payload())], why=(
            "Clicking 'Pay now' must create exactly one order through the Merchant API."
        ))
        self.assertEqual(
            rendering_values.get('api_url'), self.checkout_url,
            msg=(
                "The customer must be redirected to the checkout URL Revolut returned. Any other "
                "URL sends them to a page where they cannot pay.\n"
                f"    rendering values: {rendering_values}"
            ),
        )
        self.assertEqual(
            tx.provider_reference, self.order_id,
            msg=(
                "The order id must be stored before the customer leaves for the hosted page: it is "
                "the only handle on a payment that then happens outside of Odoo's sight."
            ),
        )

    def test_order_without_a_checkout_url_is_refused(self):
        """ Without a checkout URL there is nowhere to send the customer. """
        tx = self._create_transaction(flow='redirect')
        order_data = {k: v for k, v in self.order_data.items() if k != 'checkout_url'}

        with patch(REQUEST_PATH, return_value=order_data):
            with self.assertRaises(
                ValidationError,
                msg=(
                    "An order created without a checkout URL must raise. Rendering an empty "
                    "redirection form instead leaves the customer on a blank page with no error."
                ),
            ):
                tx._get_specific_rendering_values(None)
