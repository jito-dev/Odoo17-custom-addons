import time
from unittest.mock import patch

from werkzeug.urls import url_encode

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment.tests.http_common import PaymentHttpCommon
from odoo.addons.payment_revolut.controllers.main import RevolutController
from odoo.addons.payment_revolut.tests.common import (
    REQUEST_PATH, RevolutCommon, RevolutWebhookMixin,
)

_CONTROLLER_LOGGER = 'odoo.addons.payment_revolut.controllers.main'


@tagged('post_install', '-at_install')
class RevolutWebhookTest(RevolutCommon, RevolutWebhookMixin, PaymentHttpCommon):
    """ The controller: the signed webhook route and the customer return route. """

    def _notified_transaction(self):
        """ Return a transaction Revolut can send a notification about. """
        return self._create_transaction(flow='redirect', provider_reference=self.order_id)

    def _assert_untouched(self, tx, why):
        """ Assert that the refused notification changed nothing. """
        self.assertTxState(tx, 'draft', why=why)

    def _no_api_call(self):
        """ Patch the API away for the notifications that must be refused before reaching it.

        A refused notification must cost nothing: were the refusal to regress, the test would hit
        the real API and time out instead of failing on the assertion.
        """
        return patch(REQUEST_PATH)

    # === Signature verification === #

    @mute_logger(_CONTROLLER_LOGGER)
    def test_signed_webhook_confirms_the_transaction(self):
        tx = self._notified_transaction()

        with patch(REQUEST_PATH, return_value=self._revolut_order(state='completed')):
            response = self._post_webhook(tx)

        self.assertAcknowledged(response, why=(
            "A correctly signed notification must be accepted; a 403 here means Odoo and Revolut "
            "no longer compute the signature the same way, and no payment can be confirmed."
        ))
        self.assertTxState(tx, 'done', why=(
            "The webhook is what ultimately confirms a payment. If it stops confirming, customers "
            "pay and their orders stay unpaid in Odoo."
        ))

    @mute_logger(_CONTROLLER_LOGGER, 'odoo.http')
    def test_webhook_with_a_wrong_signature_is_refused(self):
        tx = self._notified_transaction()

        with patch(REQUEST_PATH, return_value=self._revolut_order(state='completed')):
            response = self._post_webhook(tx, secret='wsk_attacker')

        self.assertRefused(response, why=(
            "A notification signed with the wrong secret must be refused. Accepting it lets "
            "anyone who knows the URL mark any order as paid."
        ))
        self._assert_untouched(tx, why=(
            "A notification with a wrong signature must not touch the transaction at all."
        ))

    @mute_logger(_CONTROLLER_LOGGER, 'odoo.http')
    def test_replayed_webhook_is_refused(self):
        """ An old notification is refused even though its signature is valid. """
        tx = self._notified_transaction()
        an_hour_ago = str(int((time.time() - 3600) * 1000))

        with patch(REQUEST_PATH, return_value=self._revolut_order(state='completed')):
            response = self._post_webhook(tx, timestamp=an_hour_ago)

        self.assertRefused(response, why=(
            "A notification older than the replay window must be refused even though its signature "
            "is valid. Otherwise a captured notification can be replayed at any later time."
        ))
        self._assert_untouched(tx, why="A replayed notification must not touch the transaction.")

    @mute_logger(_CONTROLLER_LOGGER, 'odoo.http')
    def test_missing_signature_headers_are_refused(self):
        """ An unsigned notification proves nothing about who sent it. """
        tx = self._notified_transaction()
        body = self._webhook_body(tx)
        signed_headers = self._webhook_headers(body)

        with self._no_api_call() as api:
            for description, headers in (
                ("neither header", {'Content-Type': 'application/json'}),
                ("no signature", {
                    k: v for k, v in signed_headers.items() if k != 'Revolut-Signature'
                }),
                ("no timestamp", {
                    k: v for k, v in signed_headers.items() if k != 'Revolut-Request-Timestamp'
                }),
            ):
                with self.subTest(case=description):
                    response = self._post_webhook(tx, body=body, headers=headers)
                    self.assertRefused(response, why=(
                        f"A notification with {description} must be refused: both headers are "
                        f"needed to tell an authentic notification from a forged one."
                    ))

        self.assertNoApiCall(api, why=(
            "An unsigned notification must be refused before anything is asked of the API."
        ))
        self._assert_untouched(tx, why="An unsigned notification must not touch the transaction.")

    @mute_logger(_CONTROLLER_LOGGER, 'odoo.http')
    def test_unreadable_timestamp_is_refused(self):
        """ The replay window cannot be checked at all if the timestamp is not a number. """
        tx = self._notified_transaction()

        with self._no_api_call() as api:
            response = self._post_webhook(tx, timestamp='not-a-timestamp')

        self.assertRefused(response, why=(
            "A timestamp that is not a number must be refused, not treated as zero or as now: "
            "either would disable the replay protection entirely."
        ))
        self.assertNoApiCall(api, why="The refusal must happen before any call to the API.")
        self._assert_untouched(tx, why="A notification refused this way must change nothing.")

    @mute_logger(_CONTROLLER_LOGGER, 'odoo.http')
    def test_webhook_without_a_configured_secret_is_refused(self):
        """ With no secret to check against, no notification can be trusted. """
        tx = self._notified_transaction()
        self.provider.sudo().revolut_webhook_secret = False

        with self._no_api_call() as api:
            response = self._post_webhook(tx)

        self.assertRefused(response, why=(
            "With no signing secret stored, every notification must be refused. Accepting them "
            "unverified turns a misconfigured provider into an open door."
        ))
        self.assertNoApiCall(api, why="The refusal must happen before any call to the API.")
        self._assert_untouched(tx, why="An unverifiable notification must change nothing.")

    @mute_logger(_CONTROLLER_LOGGER)
    def test_timestamp_in_seconds_is_accepted(self):
        """ The header is documented in milliseconds, but seconds are read as seconds. """
        tx = self._notified_transaction()

        with patch(REQUEST_PATH, return_value=self._revolut_order(state='completed')):
            response = self._post_webhook(tx, timestamp=str(int(time.time())))

        self.assertAcknowledged(response, why=(
            "A timestamp sent in seconds must be understood as seconds. Read as milliseconds, it "
            "dates the notification to 1970 and every payment is refused as a replay."
        ))
        self.assertTxState(tx, 'done', why="A notification within the replay window must be processed.")

    @mute_logger(_CONTROLLER_LOGGER)
    def test_one_matching_signature_among_several_is_enough(self):
        """ During a secret rotation Revolut signs with both secrets; one match must do. """
        tx = self._notified_transaction()

        with patch(REQUEST_PATH, return_value=self._revolut_order(state='completed')):
            response = self._post_webhook(tx, extra_secrets=('wsk_previous',))

        self.assertAcknowledged(response, why=(
            "The header can hold several comma-separated signatures and one match must be enough. "
            "Requiring all of them to match makes every secret rotation drop payments."
        ))
        self.assertTxState(tx, 'done', why="A notification with one valid signature must be processed.")

    @mute_logger(_CONTROLLER_LOGGER, 'odoo.http')
    def test_tampered_body_is_refused(self):
        """ The signature covers the raw bytes, so an edited body no longer matches. """
        tx = self._notified_transaction()
        signed_body = self._webhook_body(tx)
        tampered_body = self._webhook_body(tx, event='ORDER_CANCELLED')

        with self._no_api_call() as api:
            response = self._post_webhook(
                tx, body=tampered_body, headers=self._webhook_headers(signed_body)
            )

        self.assertRefused(response, why=(
            "A body edited after signing must be refused: the signature has to be checked against "
            "the raw bytes received, never against a re-serialized payload.\n"
            f"    signed body:  {signed_body}\n"
            f"    body sent:    {tampered_body}"
        ))
        self.assertNoApiCall(api, why="A tampered notification must be refused before reaching the API.")
        self._assert_untouched(tx, why="A tampered notification must not touch the transaction.")

    # === Acknowledged notifications === #

    @mute_logger(_CONTROLLER_LOGGER)
    def test_unhandled_event_is_acknowledged_without_processing(self):
        """ Payout events are about the merchant's own settlements, not about a transaction. """
        tx = self._notified_transaction()

        with self._no_api_call() as api:
            response = self._post_webhook(tx, body=self._webhook_body(tx, event='PAYOUT_COMPLETED'))

        self.assertAcknowledged(response, why=(
            "An event this module does not handle must still be acknowledged, or Revolut retries "
            "it until it gives up and disables the webhook."
        ))
        self.assertNoApiCall(api, why=(
            "An unhandled event must cost nothing: it says nothing about any transaction, so "
            "there is no order to fetch."
        ))
        self._assert_untouched(tx, why=(
            "A payout event is about the merchant's own settlement and must not move a customer's "
            "transaction."
        ))

    @mute_logger(_CONTROLLER_LOGGER)
    def test_unknown_order_is_acknowledged(self):
        """ Answering with an error would only make Revolut retry a notification forever. """
        response = self._post_webhook(body=self._webhook_body(
            order_id='unknown-order-id', merchant_order_ext_ref='unknown-reference'
        ))

        self.assertAcknowledged(response, why=(
            "A notification matching no transaction must be acknowledged, not answered with an "
            "error. Databases sharing one merchant account each receive the others' notifications, "
            "and retrying them forever is what gets a webhook disabled."
        ))

    # === The return route === #

    def _return_from_checkout(self, **params):
        """ Follow the redirection Revolut sends the customer back with. """
        url = self._build_url(RevolutController._return_url)
        if params:
            url = f'{url}?{url_encode(params)}'
        return self.url_open(url, allow_redirects=False)

    def assertRedirectsToStatusPage(self, response, why):
        location = response.headers.get('Location', '(no Location header)')
        self.assertIn('/payment/status', location, msg=(
            f"{why}\n"
            f"    expected a redirection to /payment/status\n"
            f"    HTTP status: {response.status_code}\n"
            f"    Location:    {location}"
        ))

    @mute_logger(_CONTROLLER_LOGGER)
    def test_return_redirects_to_the_status_page(self):
        tx = self._notified_transaction()

        with patch(REQUEST_PATH, return_value=self._revolut_order(state='completed')):
            response = self._return_from_checkout(reference=tx.reference)

        self.assertRedirectsToStatusPage(response, why=(
            "The customer coming back from the hosted page must land on the payment status page."
        ))
        self.assertTxState(tx, 'done', why=(
            "The return route refetches the order from the API, so a payment already settled is "
            "confirmed without waiting for the webhook."
        ))

    @mute_logger(_CONTROLLER_LOGGER)
    def test_return_redirects_even_when_the_data_are_unusable(self):
        """ The customer must reach the status page even when Odoo cannot use what came back. """
        tx = self._notified_transaction()

        with self._no_api_call() as api:
            response = self._return_from_checkout()

        self.assertRedirectsToStatusPage(response, why=(
            "Return data Odoo cannot match must still send the customer to the status page. An "
            "error page here reads, to the customer, as a payment that failed."
        ))
        self.assertNoApiCall(api, why="There is no order to fetch when the data match no transaction.")
        self._assert_untouched(tx, why="Unusable return data must not change any transaction.")
