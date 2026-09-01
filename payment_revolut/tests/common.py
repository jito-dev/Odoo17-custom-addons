import hashlib
import hmac
import json
import pprint
import time

import requests

from odoo.addons.payment.tests.common import PaymentCommon
from odoo.addons.payment_revolut.controllers.main import RevolutController

# The business logic is tested against a mocked API call, as the core payment providers do.
REQUEST_PATH = (
    'odoo.addons.payment_revolut.models.payment_provider.PaymentProvider._revolut_make_request'
)
# The HTTP layer itself is tested one level lower, where the real `requests` call would happen.
HTTP_REQUEST_PATH = 'odoo.addons.payment_revolut.models.payment_provider.requests.request'


class RevolutCommon(PaymentCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.revolut = cls._prepare_provider('revolut', update_values={
            'revolut_secret_key': 'sk_dummy',
            'revolut_webhook_secret': 'wsk_dummy',
        })
        cls.provider = cls.revolut
        cls.currency = cls.currency_euro

        # Revolut refuses a return URL on `localhost`, which is what a test database resolves to.
        cls.base_url_value = 'https://odoo.example.com'
        cls.env['ir.config_parameter'].sudo().set_param('web.base.url', cls.base_url_value)

        cls.order_id = '6a7f39f4-e708-aa33-a066-b846c421cc16'
        cls.checkout_url = 'https://sandbox-checkout.revolut.com/payment-link/e9a74445'

        # An order as returned by `POST /api/orders`, trimmed to the keys the module reads.
        cls.order_data = {
            'id': cls.order_id,
            'token': 'e9a74445-a2c0-4e00-ac0b-f7128e7ca603',
            'state': 'pending',
            'amount': 111111,
            'currency': 'EUR',
            'checkout_url': cls.checkout_url,
        }

        # A refund answers with an order of its own, with its own id.
        cls.refund_order_id = 'b1c3d5e7-1234-4a56-89ab-0f1e2d3c4b5a'
        cls.refund_order_data = {
            'id': cls.refund_order_id,
            'state': 'completed',
            'amount': 111111,
            'currency': 'EUR',
        }

        # A webhook notification as sent by Revolut.
        cls.notification_data = {
            'event': 'ORDER_COMPLETED',
            'order_id': cls.order_id,
            'merchant_order_ext_ref': cls.reference,
        }

        # The webhook management endpoints, as seen from this database.
        cls.webhook_id = '4b2e5c6a-9f31-4f1e-8a2b-7c6d5e4f3a2b'
        cls.webhook_url = f'{cls.base_url_value}{RevolutController._webhook_url}'
        cls.webhooks_list_data = [
            {'id': 'another-webhook', 'url': 'https://other.example.com/payment/revolut/webhook'},
            {'id': cls.webhook_id, 'url': cls.webhook_url},
        ]
        cls.rotated_webhook_data = {'id': cls.webhook_id, 'signing_secret': 'wsk_rotated'}
        cls.created_webhook_data = {'id': cls.webhook_id, 'signing_secret': 'wsk_created'}

    def _revolut_order(self, **values):
        """ Return a copy of the sample order data updated with `values`. """
        return dict(self.order_data, **values)

    # === Assertions ===
    #
    # Every assertion below takes a `why`: one sentence naming the rule that is broken when the
    # test fails, written for whoever reads the failure without knowing this module. The rest of
    # the message is the context needed to tell a broken rule from a broken test.

    def assertTxState(self, tx, expected_state, why):
        """ Assert the state of a transaction, read back from the database. """
        tx.invalidate_recordset()  # The controller writes from another environment.
        self.assertEqual(tx.state, expected_state, msg=(
            f"{why}\n"
            f"    transaction:    {tx.reference} ({tx.operation}, {tx.amount} {tx.currency_id.name})"
            f"\n"
            f"    expected state: {expected_state}\n"
            f"    actual state:   {tx.state}\n"
            f"    state message:  {tx.state_message or '(none)'}\n"
            f"    order id:       {tx.provider_reference or '(none)'}"
        ))

    def assertApiCalls(self, api, expected_calls, why):
        """ Assert the exact sequence of requests made to the Merchant API.

        :param api: The mock that replaced `_revolut_make_request`.
        :param list expected_calls: The expected calls, as `unittest.mock.call` objects.
        :param str why: What it means for the module when this does not hold.
        """
        self.assertEqual(list(api.call_args_list), list(expected_calls), msg=(
            f"{why}\n"
            f"    expected requests:\n{self._format_calls(expected_calls)}\n"
            f"    actual requests:\n{self._format_calls(api.call_args_list)}"
        ))

    def assertNoApiCall(self, api, why):
        """ Assert that nothing was sent to the Merchant API. """
        self.assertFalse(api.call_args_list, msg=(
            f"{why}\n"
            f"    requests that were made nonetheless:\n{self._format_calls(api.call_args_list)}"
        ))

    def assertPayloadValue(self, payload, key, expected, why):
        """ Assert one value of a request payload, showing the whole payload on failure. """
        self.assertEqual(payload.get(key), expected, msg=(
            f"{why}\n"
            f"    payload key: {key!r}\n"
            f"    expected:    {expected!r}\n"
            f"    actual:      {payload.get(key)!r}\n"
            f"    full payload sent to Revolut:\n{self._indent(pprint.pformat(payload))}"
        ))

    @staticmethod
    def _format_calls(calls):
        """ Return the calls one per line, or an explicit marker when there is none. """
        if not calls:
            return '        (no request was made)'
        return '\n'.join(f'        {call_}' for call_ in calls)

    @staticmethod
    def _indent(text, prefix='        '):
        return '\n'.join(f'{prefix}{line}' for line in text.splitlines())

    @staticmethod
    def _revolut_response(status_code=200, json_data=None, content=None):
        """ Build the response the API would return, as a real `requests.Response`.

        A real response is used rather than a mock so that `raise_for_status`, `json` and `text`
        behave exactly as they do in production, including the errors they raise.

        :param int status_code: The HTTP status code of the response.
        :param json_data: The body of the response, to be serialized as JSON.
        :param content: The raw body of the response, for bodies that are not valid JSON.
        :return: The response.
        :rtype: requests.Response
        """
        response = requests.Response()
        response.status_code = status_code
        response.reason = 'OK' if status_code < 400 else 'Bad Request'
        response.url = 'https://sandbox-merchant.revolut.com/api/orders'
        response.headers['Content-Type'] = 'application/json'
        if content is None:
            content = b'' if json_data is None else json.dumps(json_data).encode()
        elif isinstance(content, str):
            content = content.encode()
        response._content = content
        return response


class RevolutWebhookMixin:
    """ Helpers to post a signed notification to the webhook route.

    The signature covers the raw bytes of the body, so the body is built once as a string and both
    signed and sent as-is; re-serializing it would break the signature.
    """

    def _webhook_signature(self, body, secret, timestamp):
        """ Return the signature Revolut would send for this body. """
        return 'v1=' + hmac.new(
            secret.encode(), f'v1.{timestamp}.{body}'.encode(), hashlib.sha256
        ).hexdigest()

    def _webhook_headers(self, body, secret='wsk_dummy', timestamp=None, extra_secrets=()):
        """ Return the headers of a notification signed with `secret`.

        :param str body: The body to sign, exactly as it will be sent.
        :param str secret: The signing secret to use.
        :param str timestamp: The value of the timestamp header; defaults to now, in milliseconds.
        :param tuple extra_secrets: Additional secrets to sign the body with, listed before the
                                    signature of `secret`, as Revolut does during a rotation.
        :return: The headers.
        :rtype: dict
        """
        timestamp = timestamp if timestamp is not None else str(int(time.time() * 1000))
        signatures = [
            self._webhook_signature(body, s, timestamp) for s in (*extra_secrets, secret)
        ]
        return {
            'Content-Type': 'application/json',
            'Revolut-Request-Timestamp': timestamp,
            'Revolut-Signature': ','.join(signatures),
        }

    def _webhook_body(self, tx=None, **values):
        """ Return the body of a notification about `tx`, updated with `values`. """
        if tx is not None:
            values.setdefault('merchant_order_ext_ref', tx.reference)
        return json.dumps(dict(self.notification_data, **values))

    def _post_webhook(self, tx=None, body=None, headers=None, **header_values):
        """ Post a notification about `tx` to the webhook route.

        :param recordset tx: The transaction the notification is about, if any.
        :param str body: The body to send; defaults to a notification about `tx`.
        :param dict headers: The headers to send; defaults to headers signing `body`.
        :param dict header_values: The values passed to `_webhook_headers` to build the headers.
        :return: The response of the request.
        :rtype: requests.Response
        """
        body = self._webhook_body(tx) if body is None else body
        if headers is None:
            headers = self._webhook_headers(body, **header_values)
        response = self.url_open(
            self._build_url(RevolutController._webhook_url), data=body, headers=headers
        )
        # Kept for the assertion messages: a failure is unreadable without what was actually sent.
        self._last_webhook_body = body
        self._last_webhook_headers = headers
        return response

    def assertRefused(self, response, why):
        """ Assert that the notification was refused outright, without being processed. """
        self.assertEqual(response.status_code, 403, msg=(
            f"{why}\n"
            f"    expected HTTP 403 (Forbidden), got HTTP {response.status_code}\n"
            f"{self._describe_last_webhook()}"
        ))

    def assertAcknowledged(self, response, why):
        """ Assert that the notification was acknowledged, so that Revolut stops retrying it. """
        self.assertEqual(response.status_code, 200, msg=(
            f"{why}\n"
            f"    expected HTTP 200, got HTTP {response.status_code}\n"
            f"{self._describe_last_webhook()}"
        ))

    def _describe_last_webhook(self):
        """ Return what the last notification carried, for an assertion message. """
        body = getattr(self, '_last_webhook_body', None)
        if body is None:
            return '    (no notification was posted)'
        headers = getattr(self, '_last_webhook_headers', {})
        signatures = headers.get('Revolut-Signature', '(none)').split(',')
        return (
            f"    body sent:  {body}\n"
            f"    timestamp:  {headers.get('Revolut-Request-Timestamp', '(none)')}\n"
            f"    signatures: {len(signatures)} sent"
        )
