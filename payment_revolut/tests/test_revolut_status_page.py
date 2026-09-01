from datetime import timedelta
from unittest.mock import call, patch

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment_revolut import const
from odoo.addons.payment_revolut.tests.common import REQUEST_PATH, RevolutCommon

_RECONCILE_LOGGER = 'odoo.addons.payment_revolut.models.payment_transaction_reconcile'


@tagged('post_install', '-at_install')
class RevolutStatusPageTest(RevolutCommon):
    """ The customer waiting on the payment status page.

    Revolut sends the customer back before the order is finished — the page is polled every three
    seconds while they wait, and these tests are about what that poll is allowed to do: ask the
    API again, but not once per poll, and never break the page when the answer is bad.
    """

    def _pending_transaction(self):
        tx = self._create_transaction(flow='redirect', provider_reference=self.order_id)
        tx._set_pending()
        return tx

    # === Asking again === #

    def test_a_pending_transaction_is_refreshed_when_the_page_polls(self):
        tx = self._pending_transaction()
        with patch(REQUEST_PATH, return_value=self._revolut_order(state='completed')) as api:
            tx._get_post_processing_values()
        self.assertApiCalls(api, [call(f'orders/{self.order_id}', method='GET')], (
            "The status page must ask Revolut again about a pending transaction. Without it the "
            "customer reads 'waiting for approval' until the reconciliation cron runs — up to "
            "fifteen minutes for a payment that settled seconds after they left the card form."
        ))
        self.assertTxState(tx, 'done', (
            "A transaction the API reports as completed must be confirmed from the status page, "
            "not merely re-read: the whole point is that the customer sees the result now."
        ))

    def test_the_confirmed_transaction_is_post_processed_in_the_same_request(self):
        tx = self._pending_transaction()
        with patch(REQUEST_PATH, return_value=self._revolut_order(state='completed')):
            tx._get_post_processing_values()
        self.assertTrue(tx.is_post_processed, (
            "Post-processing must run in the same request that confirms the payment. "
            "`poll_status` decides whether to post-process *before* it reads these values, so "
            "otherwise the customer is redirected to an invoice that is still unpaid and stays "
            "that way until the post-processing cron runs."
        ))

    # === Not asking too often === #

    def test_a_second_poll_within_the_interval_asks_nothing(self):
        tx = self._pending_transaction()
        with patch(REQUEST_PATH, return_value=self._revolut_order()) as api:
            tx._get_post_processing_values()
            tx._get_post_processing_values()
        self.assertApiCalls(api, [call(f'orders/{self.order_id}', method='GET')], (
            "The page polls every three seconds; answering each poll with an API call would turn "
            "one payment into a dozen requests. The second poll inside "
            f"const.POLL_STATUS_MIN_INTERVAL_SECONDS ({const.POLL_STATUS_MIN_INTERVAL_SECONDS}s) "
            "must be served from what Odoo already knows."
        ))

    def test_the_next_poll_after_the_interval_asks_again(self):
        tx = self._pending_transaction()
        with patch(REQUEST_PATH, return_value=self._revolut_order()) as api:
            tx._get_post_processing_values()
            tx.revolut_last_poll = fields.Datetime.now() - timedelta(
                seconds=const.POLL_STATUS_MIN_INTERVAL_SECONDS + 1
            )
            tx._get_post_processing_values()
        self.assertEqual(len(api.mock_calls), 2, msg=(
            "Once the interval has elapsed the API must be asked again, otherwise the throttle "
            "is not a throttle but a single lookup and the customer waits for the cron anyway.\n"
            f"    calls made: {len(api.mock_calls)}"
        ))

    # === What must not be asked about === #

    def test_a_finished_transaction_is_not_refreshed(self):
        tx = self._create_transaction(flow='redirect', provider_reference=self.order_id)
        tx._set_done()
        with patch(REQUEST_PATH) as api:
            tx._get_post_processing_values()
        self.assertNoApiCall(api, (
            "A transaction that already reached a final state has nothing left to learn from the "
            "API. Asking anyway spends a request per poll on every finished payment."
        ))

    def test_a_transaction_without_an_order_is_not_refreshed(self):
        tx = self._create_transaction(flow='redirect')
        tx._set_pending()
        with patch(REQUEST_PATH) as api:
            tx._get_post_processing_values()
        self.assertNoApiCall(api, (
            "With no order id there is nothing to ask Revolut about — the customer never reached "
            "the hosted page. A request here could only fail."
        ))

    def test_a_transaction_of_another_provider_is_left_alone(self):
        tx = self._create_transaction(
            flow='redirect',
            provider_id=self.dummy_provider.id,
            payment_method_id=self.dummy_provider.payment_method_ids[:1].id,
        )
        tx._set_pending()
        with patch(REQUEST_PATH) as api:
            tx._get_post_processing_values()
        self.assertNoApiCall(api, (
            "This override runs for every provider's status page. Touching a transaction that is "
            "not Revolut's would send another provider's payment through this module's API."
        ))

    # === When the API misbehaves === #

    @mute_logger(_RECONCILE_LOGGER)
    def test_an_api_failure_never_breaks_the_status_page(self):
        tx = self._pending_transaction()
        with patch(REQUEST_PATH, side_effect=ValidationError("Revolut is down")):
            values = tx._get_post_processing_values()
        self.assertEqual(values['state'], 'pending', msg=(
            "A failing API must leave the customer looking at the page they were on, with the "
            "state unchanged. Letting the error out replaces the payment status with a traceback "
            "for a payment that is probably fine — and the cron would have sorted it out anyway."
        ))
        self.assertTrue(values.get('reference'), (
            "The page still needs its values after a failed refresh; returning a broken dict is "
            "the same outage as raising."
        ))
