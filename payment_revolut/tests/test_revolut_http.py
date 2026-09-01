from unittest.mock import patch

import requests

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment_revolut import const
from odoo.addons.payment_revolut.tests.common import HTTP_REQUEST_PATH, RevolutCommon

_PROVIDER_LOGGER = 'odoo.addons.payment_revolut.models.payment_provider'


@tagged('post_install', '-at_install')
class RevolutHttpTest(RevolutCommon):
    """ The HTTP layer: what goes on the wire, and what happens when it comes back wrong.

    This is the one place where `requests.request` itself is patched, so that the error handling
    of `_revolut_make_request` is actually executed instead of being mocked away.
    """

    def test_request_sends_the_required_headers(self):
        """ Revolut rejects a request without the API version, and identifies the integration. """
        with patch(HTTP_REQUEST_PATH, return_value=self._revolut_response()) as http_request:
            self.provider._revolut_make_request('orders', payload={'amount': 111111})

        kwargs = http_request.call_args.kwargs
        headers = kwargs['headers']
        context = f"\n    headers actually sent:\n{self._indent(self._format_headers(headers))}"
        self.assertEqual(
            headers.get('Authorization'), 'Bearer sk_dummy',
            msg="Every request is authenticated with the secret API key as a bearer token." + context,
        )
        self.assertEqual(
            headers.get('Revolut-Api-Version'), const.API_VERSION,
            msg=(
                "Revolut rejects any request without the 'Revolut-Api-Version' header, and the "
                "payload shape depends on it, which is why it is pinned in `const.py`." + context
            ),
        )
        self.assertEqual(
            headers.get('Content-Type'), 'application/json',
            msg="The Merchant API only accepts JSON bodies." + context,
        )
        self.assertIn(
            'RevolutOdoo/', headers.get('User-Agent', ''),
            msg=(
                "The User-Agent identifies this integration and its version to Revolut's support."
                + context
            ),
        )
        self.assertEqual(
            kwargs.get('json'), {'amount': 111111},
            msg="The payload must be sent as a JSON body, not as form data or a query string.",
        )
        self.assertEqual(
            kwargs.get('timeout'), 60,
            msg=(
                "Every request must be bounded by a timeout. Without one, an unresponsive API "
                "holds a worker (and a database transaction) open indefinitely."
            ),
        )

    def test_request_builds_the_endpoint_url(self):
        """ The endpoint is appended to the API host, whether or not it has a leading slash. """
        expected_urls = {
            'orders': f'{const.API_URLS["sandbox"]}/api/orders',
            '/orders': f'{const.API_URLS["sandbox"]}/api/orders',
            f'orders/{self.order_id}/capture':
                f'{const.API_URLS["sandbox"]}/api/orders/{self.order_id}/capture',
            '1.0/webhooks': f'{const.API_URLS["sandbox"]}/api/1.0/webhooks',
        }
        for endpoint, expected_url in expected_urls.items():
            with self.subTest(endpoint=endpoint):
                with patch(HTTP_REQUEST_PATH, return_value=self._revolut_response()) as http_request:
                    self.provider._revolut_make_request(endpoint, method='GET')
                self.assertEqual(
                    http_request.call_args.args, ('GET', expected_url),
                    msg=(
                        f"The endpoint {endpoint!r} must resolve to {expected_url!r}. A URL built "
                        f"wrong reaches the API as a 404, which surfaces to the merchant as an "
                        f"unexplained communication failure."
                    ),
                )

    def test_empty_response_body_yields_an_empty_dict(self):
        """ A successful DELETE answers 204 with an empty body, which is not valid JSON. """
        with patch(HTTP_REQUEST_PATH, return_value=self._revolut_response(status_code=204)):
            result = self.provider._revolut_make_request('1.0/webhooks/x', method='DELETE')

        self.assertEqual(
            result, {},
            msg=(
                "An empty body must be read as an empty dict. Calling `json()` on it raises, which "
                "would turn a successful call into an error the caller cannot make sense of."
            ),
        )

    @mute_logger(_PROVIDER_LOGGER)
    def test_http_error_is_reported_as_a_validation_error(self):
        """ The message Revolut sends is the only hint the merchant gets; it must reach them. """
        response = self._revolut_response(400, json_data={'message': "The amount is invalid"})

        with patch(HTTP_REQUEST_PATH, return_value=response):
            with self.assertRaises(
                ValidationError,
                msg=(
                    "An HTTP error must be raised as a ValidationError. Swallowed, the caller "
                    "carries on as if the order, capture or refund had succeeded."
                ),
            ) as error:
                self.provider._revolut_make_request('orders', payload={'amount': -1})

        self.assertIn(
            "The amount is invalid", str(error.exception),
            msg=(
                "The message Revolut sent must reach the user unchanged: it is the only thing that "
                "says what is actually wrong with the request.\n"
                f"    message raised: {error.exception}"
            ),
        )

    def test_error_message_falls_back_to_the_raw_body(self):
        """ Some errors carry only an `errorId`, and gateway errors are not JSON at all. """
        cases = [
            (self._revolut_response(400, json_data={'errorId': 'abc-123'}), 'abc-123',
             "an error with an `errorId` but no `message`"),
            (self._revolut_response(502, content='<html>Bad gateway</html>'), 'Bad gateway',
             "a gateway error whose body is not JSON at all"),
        ]
        for response, expected_fragment, description in cases:
            with self.subTest(case=description):
                message = self.provider._revolut_extract_error_message(response)
                self.assertIn(
                    expected_fragment, message,
                    msg=(
                        f"For {description}, the raw body must be shown rather than nothing. An "
                        f"empty error message leaves support with no lead at all.\n"
                        f"    extracted message: {message!r}"
                    ),
                )

    def test_error_message_is_truncated(self):
        """ A raw body can be a whole HTML page; it is not a message for a merchant. """
        message = self.provider._revolut_extract_error_message(
            self._revolut_response(502, content='x' * 500)
        )

        self.assertEqual(
            len(message), 300,
            msg=(
                "A raw error body must be cut to 300 characters. A full HTML error page pasted "
                "into a user-facing dialog is unreadable.\n"
                f"    extracted length: {len(message)}"
            ),
        )

    @mute_logger(_PROVIDER_LOGGER)
    def test_network_failures_are_reported_as_a_validation_error(self):
        """ A connection that never opens must be as loud as an error that comes back. """
        for error_class in (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            with self.subTest(error=error_class.__name__):
                with patch(HTTP_REQUEST_PATH, side_effect=error_class()):
                    with self.assertRaises(
                        ValidationError,
                        msg=(
                            f"A {error_class.__name__} must surface as a ValidationError. "
                            f"Unhandled, it reaches the customer as a server error page in the "
                            f"middle of a payment."
                        ),
                    ) as error:
                        self.provider._revolut_make_request('orders')

                self.assertIn(
                    "Could not establish the connection", str(error.exception),
                    msg=(
                        "The message must say that Revolut could not be reached, so that support "
                        "looks at the network rather than at the payload.\n"
                        f"    message raised: {error.exception}"
                    ),
                )

    @staticmethod
    def _format_headers(headers):
        """ Return the headers one per line, with the credentials masked. """
        return '\n'.join(
            f'{key}: {"Bearer ***" if key == "Authorization" else value}'
            for key, value in sorted(headers.items())
        )
