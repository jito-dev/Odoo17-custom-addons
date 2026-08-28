from unittest.mock import call, patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment_revolut import const
from odoo.addons.payment_revolut.tests.common import REQUEST_PATH, RevolutCommon


@tagged('post_install', '-at_install')
class RevolutStatesTest(RevolutCommon):
    """ What comes back from Revolut: the state of the order, and which transaction it is about.

    The order sent to Revolut in the first place lives in `test_revolut.py`.
    """

    # === State mapping === #

    def _process(self, tx, order_state, **order_values):
        """ Run the notification processing with an order in the given state. """
        tx._handle_notification_data('revolut', {
            'order_id': self.order_id,
            'order_data': self._revolut_order(state=order_state, **order_values),
        })

    def test_completed_order_confirms_the_transaction(self):
        tx = self._create_transaction(flow='redirect')
        self._process(tx, 'completed')
        self.assertTxState(tx, 'done', why=(
            "'completed' means Revolut has the money. Anything but `done` leaves a paid order "
            "unconfirmed and unposted in accounting."
        ))

    def test_pending_order_leaves_the_transaction_pending(self):
        tx = self._create_transaction(flow='redirect')
        self._process(tx, 'processing')
        self.assertTxState(tx, 'pending', why=(
            "'processing' means Revolut has not finished; the transaction waits for the event that "
            "says how it ended."
        ))

    def test_authorised_order_is_pending_with_automatic_capture(self):
        tx = self._create_transaction(flow='redirect')
        self._process(tx, 'authorised')
        self.assertTxState(tx, 'pending', why=(
            "With automatic capture, 'authorised' only means the money is reserved: Revolut still "
            "has to capture it. Confirming here posts a payment that may never settle."
        ))

    def test_authorised_order_is_authorized_with_manual_capture(self):
        self.provider.capture_manually = True
        tx = self._create_transaction(flow='redirect')
        self._process(tx, 'authorised')
        self.assertTxState(tx, 'authorized', why=(
            "With manual capture, 'authorised' is the final state until someone captures. Left "
            "pending, the Capture button never appears on the transaction."
        ))

    def test_cancelled_order_cancels_the_transaction(self):
        tx = self._create_transaction(flow='redirect')
        self._process(tx, 'cancelled')
        self.assertTxState(tx, 'cancel', why=(
            "A cancelled order must cancel the transaction, so the document it belongs to stops "
            "waiting for a payment that will never come."
        ))

    @mute_logger('odoo.addons.payment_revolut.models.payment_transaction')
    def test_failed_order_with_a_payment_attempt_sets_the_transaction_in_error(self):
        tx = self._create_transaction(flow='redirect')
        self._process(tx, 'failed', payments=[{'state': 'failed'}])
        self.assertTxState(tx, 'error', why=(
            "A failed payment must be visible as an error, which is what invites the customer to "
            "try again."
        ))

    def test_failed_order_nobody_ever_paid_cancels_the_transaction(self):
        """ An order that expires unpaid is not an error to investigate; it is an abandoned cart.

        Revolut sends `ORDER_FAILED` when the order reaches the end of its life. With no payment
        attempt on it, nothing failed: the customer simply never paid, and the document has to stop
        waiting for money that was never sent.
        """
        tx = self._create_transaction(flow='redirect')
        self._process(tx, 'failed', payments=[])
        self.assertTxState(tx, 'cancel', why=(
            "An order that expired without a single payment attempt must cancel the transaction, "
            "not put it in error: nothing went wrong, and an error would send whoever reads it "
            "looking for a failure that never happened."
        ))

    @mute_logger('odoo.addons.payment_revolut.models.payment_transaction')
    def test_declined_payment_on_a_live_order_sets_the_transaction_in_error(self):
        """ The order stays open for a retry, but the customer's card was refused.

        Revolut keeps the order `pending` after a decline so that the customer can try again on
        the same page. Reading the order state alone would leave Odoo telling them their payment
        is being processed, and leave the invoice waiting for money nobody took.
        """
        tx = self._create_transaction(flow='redirect')
        self._process(tx, 'pending', payments=[
            {'state': 'declined', 'decline_reason': 'insufficient_funds'},
        ])
        self.assertTxState(tx, 'error', why=(
            "A declined attempt must put the transaction in error even while Revolut keeps the "
            "order open: `pending` here means 'your payment is being processed', which is exactly "
            "what did not happen."
        ))

    def test_successful_retry_after_a_decline_confirms_the_transaction(self):
        """ Only the last attempt decides: an earlier decline must not shadow a payment that went
        through. """
        tx = self._create_transaction(flow='redirect')
        self._process(tx, 'completed', payments=[
            {'state': 'declined', 'decline_reason': 'insufficient_funds'},
            {'state': 'completed'},
        ])
        self.assertTxState(tx, 'done', why=(
            "A customer who is declined once and pays on the second try has paid. Letting the "
            "first attempt decide would leave a paid order unconfirmed."
        ))

    def test_card_brand_is_taken_from_the_payment(self):
        tx = self._create_transaction(flow='redirect')

        self._process(tx, 'completed', payments=[
            {'payment_method': {'type': 'card', 'card_brand': 'visa'}},
        ])

        self.assertEqual(
            tx.payment_method_id.code, 'visa',
            msg=(
                "The brand Revolut reports must replace the method assumed at checkout, otherwise "
                "every card payment is reported under the generic 'card' method.\n"
                f"    method recorded: {tx.payment_method_id.code}"
            ),
        )

    def test_order_is_fetched_when_the_notification_carries_no_data(self):
        """ A webhook only says that something happened; the state comes from the API. """
        tx = self._create_transaction(flow='redirect')
        tx.provider_reference = self.order_id

        with patch(REQUEST_PATH, return_value=self._revolut_order(state='completed')) as api:
            tx._handle_notification_data('revolut', {'order_id': self.order_id})

        self.assertApiCalls(api, [call(f'orders/{self.order_id}', method='GET')], why=(
            "A notification carries no state, so the order must be refetched from the API. Acting "
            "on the posted payload instead would let anyone who forges one confirm a payment."
        ))
        self.assertTxState(tx, 'done', why="The state fetched from Revolut must be applied.")

    # === Transaction matching === #

    def test_transaction_is_matched_on_the_order_id_first(self):
        """ A refund has an order of its own; matching on the reference alone would route its
        events to the transaction it refunds. """
        source_tx = self._create_transaction(flow='redirect', provider_reference=self.order_id)
        refund_tx = source_tx._create_child_transaction(11.11, is_refund=True)
        refund_tx.provider_reference = self.refund_order_id

        matched_tx = self.env['payment.transaction']._get_tx_from_notification_data(
            'revolut', {'order_id': self.refund_order_id, 'reference': source_tx.reference}
        )

        self.assertEqual(
            matched_tx, refund_tx,
            msg=(
                "The order id must be matched before the reference. A refund keeps the reference "
                "of the payment it refunds, so matching on the reference sends the refund's events "
                "to the original payment — which then looks refunded when it is not.\n"
                f"    matched: {matched_tx.reference} ({matched_tx.operation})\n"
                f"    wanted:  {refund_tx.reference} ({refund_tx.operation})"
            ),
        )

    def test_transaction_is_matched_on_the_reference_when_no_order_id(self):
        """ The customer coming back from the checkout page only carries the reference. """
        tx = self._create_transaction(flow='redirect')

        matched_tx = self.env['payment.transaction']._get_tx_from_notification_data(
            'revolut', {'reference': tx.reference}
        )

        self.assertEqual(
            matched_tx, tx,
            msg=(
                "The reference must still match when there is no order id, which is all the "
                "customer's return URL carries.\n"
                f"    matched: {matched_tx.reference or '(nothing)'}"
            ),
        )

    def test_unmatched_notification_data_are_refused(self):
        """ Acting on a notification that matches nothing would act on the wrong transaction. """
        self._create_transaction(flow='redirect', provider_reference=self.order_id)

        with self.assertRaises(
            ValidationError,
            msg=(
                "Data matching no transaction must raise rather than return an arbitrary one. "
                "Returning the wrong transaction confirms a payment nobody made."
            ),
        ):
            self.env['payment.transaction']._get_tx_from_notification_data(
                'revolut', {'order_id': 'an-unknown-order', 'reference': 'an-unknown-reference'}
            )

    # === Currencies === #

    def test_unsupported_currencies_are_filtered_out(self):
        """ Revolut does not accept UAH; an order in it would fail at checkout time. """
        supported = self.provider._get_supported_currencies().mapped('name')

        self.assertIn(
            'EUR', supported,
            msg="EUR is accepted by Revolut and must stay available, or nobody can pay in euros.",
        )
        self.assertNotIn(
            'UAH', supported,
            msg=(
                "UAH is not accepted by the Merchant API. Offered on the checkout page, it lets a "
                "customer start a payment that Revolut then refuses."
            ),
        )

    def test_every_supported_currency_is_accepted_by_revolut(self):
        """ Nothing outside the list read from the API may reach the checkout page. """
        offered = self.provider._get_supported_currencies().mapped('name')
        unsupported = sorted(set(offered) - set(const.SUPPORTED_CURRENCIES))

        self.assertFalse(
            unsupported,
            msg=(
                "Every currency offered for Revolut must be one the Merchant API accepts. These "
                f"are not in `const.SUPPORTED_CURRENCIES`: {', '.join(unsupported)}."
            ),
        )
