import hashlib
import hmac
import logging
import pprint
import time

from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.payment_revolut import const

_logger = logging.getLogger(__name__)


class RevolutController(http.Controller):
    _return_url = '/payment/revolut/return'
    _webhook_url = '/payment/revolut/webhook'

    @http.route(
        _return_url, type='http', auth='public', methods=['GET', 'POST'], csrf=False,
        save_session=False
    )
    def revolut_return_from_checkout(self, **data):
        """ Process the customer coming back from the Revolut hosted payment page.

        The route is flagged with `save_session=False` to prevent Odoo from assigning a new session
        to the customer, which would lose the transaction on the way to the status page.

        Revolut redirects the customer as soon as the payment page is done with them, which can be
        before the payment is settled; the webhook is what ultimately confirms the transaction.

        :param dict data: The transaction reference embedded in the return URL.
        """
        _logger.info(
            "Handling the redirection from Revolut for reference %s with data:\n%s",
            data.get('reference'), pprint.pformat(data)
        )
        try:
            request.env['payment.transaction'].sudo()._handle_notification_data('revolut', data)
        except ValidationError:  # The customer must reach the status page either way.
            _logger.exception(
                "Unable to handle the redirection data for reference %s; sending the customer to "
                "the status page anyway. The webhook remains responsible for the final state.",
                data.get('reference')
            )
        return request.redirect('/payment/status')

    @http.route(_webhook_url, type='http', auth='public', methods=['POST'], csrf=False)
    def revolut_webhook(self):
        """ Process the notification sent by Revolut to the webhook.

        :return: An empty JSON response to acknowledge the notification.
        :rtype: werkzeug.wrappers.Response
        """
        data = request.get_json_data()
        event = data.get('event')
        order_id = data.get('order_id')
        reference = data.get('merchant_order_ext_ref')
        _logger.info(
            "Notification received from Revolut: event %s for order %s (reference %s):\n%s",
            event, order_id, reference, pprint.pformat(data)
        )

        if event not in const.HANDLED_WEBHOOK_EVENTS:
            # Revolut only sends the events the webhook subscribes to, so this means either a
            # webhook configured by hand or a new event of the API.
            _logger.info(
                "The event %s is not handled by this module; acknowledging it without processing. "
                "Handled events: %s.", event, ', '.join(const.HANDLED_WEBHOOK_EVENTS)
            )
            return request.make_json_response('')

        notification_data = {'order_id': order_id, 'reference': reference}
        try:
            tx_sudo = request.env['payment.transaction'].sudo()._get_tx_from_notification_data(
                'revolut', notification_data
            )
            self._verify_notification_signature(
                request.httprequest.data, request.httprequest.headers, tx_sudo
            )
            tx_sudo._handle_notification_data('revolut', notification_data)
        except ValidationError:  # Acknowledge the notification to avoid getting spammed.
            _logger.exception(
                "Unable to handle the notification about order %s (reference %s); acknowledging it "
                "anyway so that Revolut stops retrying it.", order_id, reference
            )
        return request.make_json_response('')

    @staticmethod
    def _verify_notification_signature(raw_payload, headers, tx_sudo):
        """ Check that the received signature matches the expected one.

        :param bytes raw_payload: The raw body of the notification, exactly as received: the
                                  signature covers the bytes, so a re-serialized payload would not
                                  match.
        :param headers: The headers of the notification request.
        :param recordset tx_sudo: The sudoed transaction referenced by the notification data, as a
                                  `payment.transaction` record.
        :return: None
        :raise Forbidden: If the signature is missing, stale, or does not match.
        """
        reference = tx_sudo.reference
        provider_sudo = tx_sudo.provider_id

        signing_secret = provider_sudo.revolut_webhook_secret
        if not signing_secret:
            _logger.warning(
                "Refused the notification for transaction %s: no webhook signing secret is stored "
                "on the provider %s, so no notification can be trusted. Press 'Generate your "
                "webhook' on the provider form to create the webhook and store its secret.",
                reference, provider_sudo.display_name
            )
            raise Forbidden()

        received_signatures = headers.get('Revolut-Signature')
        timestamp = headers.get('Revolut-Request-Timestamp')
        missing_headers = [
            name for name, value in (
                ('Revolut-Signature', received_signatures),
                ('Revolut-Request-Timestamp', timestamp),
            ) if not value
        ]
        if missing_headers:
            _logger.warning(
                "Refused the notification for transaction %s: the header(s) %s are missing. An "
                "authentic notification from Revolut always carries both.",
                reference, ', '.join(missing_headers)
            )
            raise Forbidden()

        # Reject notifications replayed outside of the tolerance window.
        try:
            sent_at = int(timestamp)
        except (TypeError, ValueError):
            _logger.warning(
                "Refused the notification for transaction %s: the 'Revolut-Request-Timestamp' "
                "header is not a number (received %r).", reference, timestamp
            )
            raise Forbidden()
        sent_at = sent_at / 1000 if sent_at > 1e11 else sent_at  # The header is in milliseconds.
        age = time.time() - sent_at
        if abs(age) > const.WEBHOOK_TIMESTAMP_TOLERANCE:
            _logger.warning(
                "Refused the notification for transaction %s: it is dated %.0f seconds %s, outside "
                "the replay window of %s seconds. If this happens for every notification, the "
                "clock of this server is out of sync.",
                reference, abs(age), "ago" if age > 0 else "in the future",
                const.WEBHOOK_TIMESTAMP_TOLERANCE
            )
            raise Forbidden()

        payload_to_sign = f'v1.{timestamp}.{raw_payload.decode()}'
        expected_signature = 'v1=' + hmac.new(
            signing_secret.encode(), payload_to_sign.encode(), hashlib.sha256
        ).hexdigest()
        # The header holds one or more comma-separated signatures; one match is enough, which is
        # what makes a secret rotation survivable.
        received_signatures = [signature.strip() for signature in received_signatures.split(',')]
        if not any(
            hmac.compare_digest(signature, expected_signature)
            for signature in received_signatures
        ):
            _logger.warning(
                "Refused the notification for transaction %s: none of the %s received signature(s) "
                "matches the one computed from the signing secret stored on the provider %s. If "
                "the webhook was re-created or its secret rotated on Revolut's side, press "
                "'Generate your webhook' on the provider form to store the current secret. "
                "Signed payload: 'v1.%s.<%s bytes of body>'.",
                reference, len(received_signatures), provider_sudo.display_name, timestamp,
                len(raw_payload)
            )
            raise Forbidden()
