from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment_revolut.tests.common import RevolutCommon

_TRANSACTION_LOGGER = 'odoo.addons.payment_revolut.models.payment_transaction'


@tagged('post_install', '-at_install')
class RevolutNotificationTest(RevolutCommon):
    """ The processing of the order data: refused data and the payment method actually used. """

    def _process(self, tx, **order_values):
        """ Process an order, `completed` unless `order_values` says otherwise. """
        order_data = self._revolut_order(**{'state': 'completed', **order_values})
        tx._process_notification_data({'order_data': order_data})

    def assertPaymentMethod(self, tx, expected_code, why):
        """ Assert the payment method Odoo recorded for a transaction. """
        self.assertEqual(tx.payment_method_id.code, expected_code, msg=(
            f"{why}\n"
            f"    transaction:     {tx.reference}\n"
            f"    expected method: {expected_code}\n"
            f"    actual method:   {tx.payment_method_id.code or '(none)'}"
        ))

    # === Refused data === #

    def test_missing_order_id_is_refused(self):
        """ Without an order id there is nothing to ask Revolut about. """
        tx = self._create_transaction(flow='redirect')

        with self.assertRaises(
            ValidationError,
            msg=(
                "Data carrying no order id, for a transaction that has none either, must be "
                "refused. Guessing which order is meant would confirm the wrong payment."
            ),
        ) as error:
            tx._process_notification_data({})

        self.assertIn(
            "missing order id", str(error.exception),
            msg=(
                "The error must name the missing order id, so that whoever reads the log knows "
                "the notification was incomplete rather than the order unknown to Revolut.\n"
                f"    message raised: {error.exception}"
            ),
        )

    def test_missing_state_is_refused(self):
        """ The state is the whole point of the notification; acting without it is guessing. """
        tx = self._create_transaction(flow='redirect')
        order_data = {k: v for k, v in self.order_data.items() if k != 'state'}

        with self.assertRaises(
            ValidationError,
            msg=(
                "An order with no state must be refused rather than processed with a default. Any "
                "default is either a payment confirmed too early or one refused for no reason."
            ),
        ) as error:
            tx._process_notification_data({'order_data': order_data})

        self.assertIn(
            "missing state", str(error.exception),
            msg=f"The error must name the missing state.\n    message raised: {error.exception}",
        )

    @mute_logger(_TRANSACTION_LOGGER)
    def test_unknown_state_sets_the_transaction_in_error(self):
        """ A state this module does not know is not a reason to leave the customer waiting. """
        tx = self._create_transaction(flow='redirect')

        self._process(tx, state='an_unknown_state')

        self.assertTxState(tx, 'error', why=(
            "An unknown order state must put the transaction in error. Left in draft, it waits "
            "forever for a notification that has already arrived."
        ))
        self.assertIn(
            'an_unknown_state', tx.state_message,
            msg=(
                "The state message must quote the unknown state: it is the only clue that the "
                "Merchant API gained a state `const.PAYMENT_STATUS_MAPPING` does not cover.\n"
                f"    state message: {tx.state_message!r}"
            ),
        )

    def test_provider_reference_is_filled_from_the_order(self):
        """ The customer returning from the checkout page carries no order id. """
        tx = self._create_transaction(flow='redirect')
        self.assertFalse(
            tx.provider_reference, msg="This test starts from a transaction with no order id yet."
        )

        self._process(tx)

        self.assertEqual(
            tx.provider_reference, self.order_id,
            msg=(
                "The order id must be stored the first time it is seen. Without it, the "
                "transaction can never be matched from a webhook, nor captured or refunded."
            ),
        )
        self.assertTxState(tx, 'done', why="A completed order must confirm the transaction.")

    @mute_logger('odoo.addons.payment_revolut.models.payment_transaction')
    def test_order_of_another_transaction_is_refused(self):
        """ A refund keeps its own order id, whatever the order data say.

        Order data that belong to a different order are not applied at all: an order id already
        stored is the transaction's identity, and quietly following the data instead would route
        the events of a payment onto the refund that refunds it — or onto a stranger's payment.
        """
        tx = self._create_transaction(flow='redirect', provider_reference=self.refund_order_id)

        with self.assertRaises(ValidationError, msg=(
            "Order data about another order must be refused outright. Applying them would move "
            "money on a transaction that is not the one Revolut is talking about."
        )):
            self._process(tx)

        self.assertEqual(
            tx.provider_reference, self.refund_order_id,
            msg=(
                "An order id already stored must never be overwritten. A refund has an order of "
                "its own, and replacing it would route the refund's events to the payment."
            ),
        )

    # === The payment method actually used === #

    def test_payment_method_is_kept_when_there_is_no_payment_yet(self):
        """ The method is only known once a payment attempt exists on the order. """
        tx = self._create_transaction(flow='redirect')
        assumed_method = tx.payment_method_id

        self._process(tx)

        self.assertPaymentMethod(tx, assumed_method.code, why=(
            "An order with no payment attempt says nothing about the method used, so the method "
            "assumed at checkout must be kept rather than cleared."
        ))

    def test_generic_card_is_kept_without_a_brand(self):
        tx = self._create_transaction(flow='redirect')

        self._process(tx, payments=[{'payment_method': {'type': 'card'}}])

        self.assertPaymentMethod(tx, 'card', why=(
            "When Revolut reports no brand, the generic 'card' method must be recorded rather "
            "than nothing."
        ))

    def test_brand_key_is_used_as_a_fallback(self):
        """ The brand is reported as `card_brand`, but older payloads use `brand`. """
        tx = self._create_transaction(flow='redirect')

        self._process(tx, payments=[{'payment_method': {'type': 'card', 'brand': 'MASTERCARD'}}])

        self.assertPaymentMethod(tx, 'mastercard', why=(
            "The brand must also be read from the `brand` key, and matched case-insensitively. "
            "Otherwise every such payment is filed under the generic 'card' method."
        ))

    def test_revolut_pay_is_mapped_to_its_odoo_code(self):
        """ Revolut calls its own wallet `pay_with_revolut`; Odoo calls it `revolut_pay`. """
        # Enabled as a merchant accepting Revolut Pay would have it enabled.
        self.env.ref('payment.payment_method_revolut_pay').sudo().active = True
        tx = self._create_transaction(flow='redirect')

        self._process(tx, payments=[{'payment_method': {'type': 'pay_with_revolut'}}])

        self.assertPaymentMethod(tx, 'revolut_pay', why=(
            "`const.PAYMENT_METHODS_MAPPING` is what translates Revolut's own name for its wallet "
            "into Odoo's. Without the mapping the payment is filed under the method assumed at "
            "checkout, and the reports say card where the customer paid by wallet."
        ))

    @mute_logger(_TRANSACTION_LOGGER)
    def test_unknown_method_keeps_the_assumed_one(self):
        """ Reporting a method Odoo does not know is worse than reporting the assumed one. """
        tx = self._create_transaction(flow='redirect')
        assumed_method = tx.payment_method_id

        self._process(tx, payments=[{'payment_method': {'type': 'a_method_from_the_future'}}])

        self.assertPaymentMethod(tx, assumed_method.code, why=(
            "A method that matches nothing in Odoo must leave the assumed one in place. Clearing "
            "the field would lose the little that is known about how the customer paid."
        ))

    def test_payment_without_a_method_keeps_the_assumed_one(self):
        tx = self._create_transaction(flow='redirect')
        assumed_method = tx.payment_method_id

        self._process(tx, payments=[{'state': 'completed'}])

        self.assertPaymentMethod(tx, assumed_method.code, why=(
            "A payment entry with no `payment_method` block must be handled without raising: "
            "Revolut omits it while the payment is still being authorised."
        ))

    def test_the_last_payment_wins(self):
        """ A declined attempt can precede the successful one; the last is the one that paid. """
        tx = self._create_transaction(flow='redirect')

        self._process(tx, payments=[
            {'payment_method': {'type': 'card', 'card_brand': 'visa'}},
            {'payment_method': {'type': 'card', 'card_brand': 'mastercard'}},
        ])

        self.assertPaymentMethod(tx, 'mastercard', why=(
            "An order can hold several payment attempts, and it is the last one that went through. "
            "Reading the first records the card that was declined."
        ))
