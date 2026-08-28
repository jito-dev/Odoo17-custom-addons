from unittest.mock import call, patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.payment_revolut.tests.common import REQUEST_PATH, RevolutCommon


@tagged('post_install', '-at_install')
class RevolutOperationsTest(RevolutCommon):
    """ The post-payment operations: capture, void and refund. """

    def _authorized_transaction(self):
        """ Return a transaction authorised on Revolut, ready to be captured or voided. """
        self.provider.capture_manually = True
        tx = self._create_transaction(flow='redirect', provider_reference=self.order_id)
        tx._set_authorized()
        return tx

    def _pending_transaction(self):
        """ Return a transaction whose customer reached the hosted page and never paid. """
        tx = self._create_transaction(flow='redirect', provider_reference=self.order_id)
        tx._set_pending()
        return tx

    def _confirmed_transaction(self):
        """ Return a confirmed transaction, ready to be refunded. """
        tx = self._create_transaction(flow='redirect', provider_reference=self.order_id)
        tx._set_done()
        return tx

    # === Capture === #

    def test_capture_sends_the_full_amount_in_minor_units(self):
        """ Revolut only captures the full authorised amount, and always in minor units. """
        tx = self._authorized_transaction()

        with patch(REQUEST_PATH, return_value=self._revolut_order(state='completed')) as api:
            tx._send_capture_request()

        self.assertApiCalls(api, [call(f'orders/{self.order_id}/capture', payload={
            'amount': 111111,  # 1111.11 EUR.
        })], why=(
            "Capturing must charge the customer the full authorised amount, in minor units. A "
            "wrong endpoint leaves the money uncaptured; a wrong amount charges the wrong sum."
        ))

    def test_capture_confirms_the_transaction(self):
        """ The captured order comes back in the response, so no extra round trip is needed. """
        tx = self._authorized_transaction()

        with patch(REQUEST_PATH, return_value=self._revolut_order(state='completed')):
            tx._send_capture_request()

        self.assertTxState(tx, 'done', why=(
            "A successful capture must confirm the transaction straight from the order returned by "
            "Revolut. Left unconfirmed, the payment is never posted in accounting even though the "
            "customer was charged."
        ))

    def test_capture_is_left_to_the_super_call_on_another_provider(self):
        """ The override must not send a Revolut request for a transaction of another provider. """
        self.provider = self.dummy_provider
        tx = self._create_transaction(flow='redirect')

        with patch(REQUEST_PATH) as api:
            tx._send_capture_request()

        self.assertNoApiCall(api, why=(
            "The Revolut override must return early for a transaction of another provider. "
            "Reaching the API here would capture a Revolut order that has nothing to do with this "
            "transaction."
        ))

    # === Void === #

    def test_void_calls_the_cancel_endpoint(self):
        """ Cancelling an authorisation needs no payload: the whole order is released. """
        tx = self._authorized_transaction()

        with patch(REQUEST_PATH, return_value=self._revolut_order(state='cancelled')) as api:
            tx._send_void_request()

        self.assertApiCalls(api, [call(f'orders/{self.order_id}/cancel')], why=(
            "Voiding must call the cancel endpoint with no payload. Anything else leaves the "
            "customer's money reserved until Revolut expires the authorisation on its own."
        ))

    def test_void_cancels_the_transaction(self):
        tx = self._authorized_transaction()

        with patch(REQUEST_PATH, return_value=self._revolut_order(state='cancelled')):
            tx._send_void_request()

        self.assertTxState(tx, 'cancel', why=(
            "A voided authorisation must leave the transaction cancelled, so that the order or "
            "invoice it belongs to stops waiting for a payment that will never come."
        ))

    # === Cancel an abandoned order === #

    def test_cancel_pending_order_calls_the_cancel_endpoint(self):
        """ Releasing an abandoned checkout is the same cancel request as voiding. """
        tx = self._pending_transaction()

        with patch(REQUEST_PATH, return_value=self._revolut_order(state='cancelled')) as api:
            tx.action_revolut_cancel_order()

        self.assertApiCalls(api, [call(f'orders/{self.order_id}/cancel')], why=(
            "Canceling an abandoned order must reach the cancel endpoint of that order. Marking "
            "the transaction canceled in Odoo alone would leave the order payable on Revolut's "
            "side, and the customer could still be charged."
        ))

    def test_cancel_pending_order_cancels_the_transaction(self):
        """ Only a canceled transaction gives the invoice its 'Pay now' button back. """
        tx = self._pending_transaction()

        with patch(REQUEST_PATH, return_value=self._revolut_order(state='cancelled')):
            tx.action_revolut_cancel_order()

        self.assertTxState(tx, 'cancel', why=(
            "Canceling the order must cancel the transaction: Odoo hides the portal 'Pay now' "
            "button of an invoice while a transaction is pending, so a transaction left pending "
            "keeps the customer locked out of paying online."
        ))

    def test_cancel_refuses_a_transaction_that_is_not_pending(self):
        """ A payment that went through must never have its order canceled behind Odoo's back. """
        tx = self._confirmed_transaction()

        with patch(REQUEST_PATH) as api:
            with self.assertRaises(
                ValidationError,
                msg=(
                    "Canceling must be refused for a transaction that is not pending. Canceling a "
                    "confirmed payment's order desynchronises Odoo from Revolut on money that was "
                    "already taken."
                ),
            ):
                tx.action_revolut_cancel_order()

        self.assertNoApiCall(api, why=(
            "The state must be checked before anything is sent: a refused cancellation that "
            "reached the API has already done what it was refused for."
        ))

    # === Refund === #

    def test_refund_sends_a_positive_amount(self):
        """ The amount of a refund transaction is negative in Odoo, but positive for the API. """
        tx = self._confirmed_transaction()

        with patch(REQUEST_PATH, return_value=self.refund_order_data) as api:
            refund_tx = tx._send_refund_request()

        payload = api.call_args.kwargs['payload']
        self.assertEqual(
            api.call_args.args[0], f'orders/{self.order_id}/refund',
            msg="The refund must be sent against the order that was paid, not any other.",
        )
        self.assertPayloadValue(payload, 'amount', 111111, why=(
            "The refund amount must be sent positive and in minor units. Odoo stores the amount of "
            "a refund transaction as negative, and sending it as-is would have Revolut reject the "
            "refund or, worse, charge the customer again."
        ))
        self.assertPayloadValue(payload, 'currency', 'EUR', why=(
            "The refund must be sent in the currency of the transaction being refunded."
        ))
        self.assertPayloadValue(payload, 'description', refund_tx.reference, why=(
            "The refund must carry its own reference, so that it can be recognised in the Revolut "
            "portal and in the payout statement."
        ))
        self.assertLess(
            refund_tx.amount, 0,
            msg=(
                "Odoo's own convention is that a refund transaction holds a negative amount; this "
                "test would be meaningless if that stopped being true."
            ),
        )

    def test_partial_refund_sends_only_the_refunded_amount(self):
        tx = self._confirmed_transaction()

        # Revolut answers a partial refund with an order for the refunded amount, not for the
        # amount of the payment it refunds.
        partial_refund_data = dict(self.refund_order_data, amount=10000)
        with patch(REQUEST_PATH, return_value=partial_refund_data) as api:
            tx._send_refund_request(amount_to_refund=100.0)

        self.assertPayloadValue(api.call_args.kwargs['payload'], 'amount', 10000, why=(
            "A partial refund must send only the amount asked for (100.00 EUR here). Sending the "
            "full amount would give the customer back more money than was agreed."
        ))

    def test_refund_id_is_set_as_provider_reference_of_the_refund_tx(self):
        """ Later events are about the refund order, not about the order it refunds. """
        tx = self._confirmed_transaction()

        with patch(REQUEST_PATH, return_value=self.refund_order_data):
            refund_tx = tx._send_refund_request()

        self.assertEqual(
            refund_tx.provider_reference, self.refund_order_id,
            msg=(
                "Revolut answers a refund with an order of its own, and that id must be stored on "
                "the refund transaction: it is what later notifications are about."
            ),
        )
        self.assertEqual(
            tx.provider_reference, self.order_id,
            msg=(
                "The refunded transaction must keep its own order id. Overwriting it would send "
                "every later event of the original payment to the refund."
            ),
        )

    def test_refund_keeps_the_source_reference_when_revolut_returns_no_id(self):
        """ Without an id of its own, the refund stays reachable through the original order. """
        tx = self._confirmed_transaction()

        with patch(REQUEST_PATH, return_value={'state': 'completed'}):
            refund_tx = tx._send_refund_request()

        self.assertEqual(
            refund_tx.provider_reference, self.order_id,
            msg=(
                "When Revolut returns no id for the refund, the refund must fall back to the order "
                "id of the payment. Left empty, the refund could never be matched again."
            ),
        )

    def test_completed_refund_triggers_the_post_processing_cron(self):
        """ Nobody browses the portal after a refund, so the payment is posted by the cron. """
        triggers_before = self._count_cron_triggers()
        tx = self._confirmed_transaction()

        with patch(REQUEST_PATH, return_value=self.refund_order_data):
            refund_tx = tx._send_refund_request()

        self.assertTxState(refund_tx, 'done', why="A completed refund order must confirm the refund.")
        self.assertEqual(
            self._count_cron_triggers(), triggers_before + 1,
            msg=(
                "A confirmed refund must trigger `payment.cron_post_process_payment_tx`. Nobody is "
                "browsing the portal after a refund, so without the trigger the refund is never "
                "posted in accounting and the books stay wrong until someone notices."
            ),
        )

    def test_pending_refund_does_not_trigger_the_post_processing_cron(self):
        """ There is nothing to post yet while Revolut is still processing the refund. """
        triggers_before = self._count_cron_triggers()
        tx = self._confirmed_transaction()

        with patch(REQUEST_PATH, return_value=dict(self.refund_order_data, state='processing')):
            refund_tx = tx._send_refund_request()

        self.assertTxState(refund_tx, 'pending', why=(
            "A refund Revolut is still processing must stay pending until it completes."
        ))
        self.assertEqual(
            self._count_cron_triggers(), triggers_before,
            msg=(
                "Only a *confirmed* refund may trigger the post-processing cron. Triggering it "
                "while the refund is still pending would post a payment that may yet fail."
            ),
        )

    def test_refund_api_failure_leaves_no_refund_transaction_behind(self):
        """ A failed refund must fail loudly and leave nothing half-done.

        The refund transaction is created before the API call, but the error rolls the whole
        database transaction back, so no orphan refund is left for the accountant to chase.
        """
        tx = self._confirmed_transaction()

        with patch(REQUEST_PATH, side_effect=ValidationError("Revolut: API unreachable")):
            with self.assertRaises(
                ValidationError,
                msg=(
                    "A refund that Revolut refuses must raise, so that the user sees the failure "
                    "instead of a refund that silently never happened."
                ),
            ):
                tx._send_refund_request()

        self.assertFalse(
            tx.child_transaction_ids,
            msg=(
                "A failed refund must leave no refund transaction behind: an orphan draft refund "
                "reads as a refund in progress and gets chased by whoever finds it. Found: "
                f"{tx.child_transaction_ids.mapped('reference')}."
            ),
        )
        self.assertTxState(tx, 'done', why=(
            "A failed refund must not touch the state of the payment it failed to refund."
        ))

    def _count_cron_triggers(self):
        """ Return how many times the payment post-processing cron was asked to run. """
        return self.env['ir.cron.trigger'].search_count(
            [('cron_id', '=', self.env.ref('payment.cron_post_process_payment_tx').id)]
        )
