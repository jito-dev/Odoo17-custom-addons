import ipaddress
import logging
import pprint

from werkzeug.urls import url_encode, url_join, url_parse

from odoo import _, models
from odoo.exceptions import ValidationError

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment_revolut import const
from odoo.addons.payment_revolut.controllers.main import RevolutController

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    # === BUSINESS METHODS - PAYMENT FLOW === #

    def _get_specific_rendering_values(self, processing_values):
        """ Override of `payment` to return Revolut-specific rendering values.

        The payment link is created here, when the customer clicks "Pay now", and not when the
        transaction is created: an order that is never paid simply expires on Revolut's side.

        Note: `self.ensure_one()` from `_get_processing_values`

        :param dict processing_values: The generic and specific processing values of the
                                       transaction.
        :return: The dict of provider-specific rendering values.
        :rtype: dict
        """
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != 'revolut':
            return res

        payload = self._revolut_prepare_order_payload()
        _logger.info(
            "Sending '/orders' request for transaction with reference %s:\n%s",
            self.reference, pprint.pformat(payload)
        )
        order_data = self.provider_id._revolut_make_request('orders', payload=payload)
        _logger.info(
            "Response of '/orders' request for transaction with reference %s:\n%s",
            self.reference, pprint.pformat(order_data)
        )

        # Store the order id right away: it is the only handle on the payment, and the customer is
        # about to leave for the hosted page where the payment happens outside of Odoo's sight.
        self.provider_reference = order_data.get('id')

        checkout_url = order_data.get('checkout_url')
        if not checkout_url:
            raise ValidationError("Revolut: " + _(
                "The order %s was created without a checkout URL, so there is nowhere to send the "
                "customer. The payment has not started; it is safe to try again.",
                order_data.get('id') or _("(unknown)")
            ))
        return {'api_url': checkout_url}

    def _revolut_prepare_order_payload(self):
        """ Prepare the payload of the order request based on the transaction values.

        :return: The request payload.
        :rtype: dict
        """
        base_url = self._revolut_get_checked_base_url()
        # The reference travels in the return URL because Revolut redirects the customer back
        # without any hint of which order they just paid.
        return_url = f'{url_join(base_url, RevolutController._return_url)}' \
                     f'?{url_encode({"reference": self.reference})}'
        payload = {
            'amount': payment_utils.to_minor_currency_units(self.amount, self.currency_id),
            'currency': self.currency_id.name,
            'description': self.reference,
            'capture_mode': 'manual' if self.provider_id.capture_manually else 'automatic',
            'redirect_url': return_url,
            # An order nobody pays must die on its own: while the transaction is pending, Odoo
            # hides the portal 'Pay now' button of the invoice it is for.
            'expire_pending_after': const.ORDER_EXPIRE_PENDING_AFTER,
            # Both carry the Odoo reference: `merchant_order_data` is what Revolut echoes in the
            # merchant portal and in the payout statement, `metadata` is what comes back on the
            # order itself.
            'merchant_order_data': {'reference': self.reference},
            'metadata': {'odoo_reference': self.reference},
        }
        if self.partner_email:
            payload['customer'] = {
                'email': self.partner_email,
                'full_name': self.partner_name or '',
            }
        return payload

    def _revolut_get_checked_base_url(self):
        """ Return the base URL of this database, checked against what Revolut accepts.

        Revolut rejects the whole order — not just the redirection — when the return URL points at
        `localhost` or at an IP address. Checking here turns that into an actionable message at
        configuration time instead of a bare "Bad Request" the first time a customer pays.

        :return: The base URL.
        :rtype: str
        :raise ValidationError: If Revolut would reject a return URL built on this base URL.
        """
        base_url = self.provider_id.get_base_url()
        host = url_parse(base_url).host or ''
        is_ip_address = True
        try:
            ipaddress.ip_address(host.strip('[]'))
        except ValueError:
            is_ip_address = False
        if host == 'localhost' or is_ip_address:
            raise ValidationError("Revolut: " + _(
                "Revolut refuses a return URL whose host is 'localhost' or an IP address, and "
                "this database resolves to %s. Set the 'web.base.url' system parameter to the "
                "public address of this database.", base_url
            ))
        return base_url

    def _send_capture_request(self, amount_to_capture=None):
        """ Override of `payment` to send a capture request to Revolut. """
        child_capture_tx = super()._send_capture_request(amount_to_capture=amount_to_capture)
        if self.provider_code != 'revolut':
            return child_capture_tx

        payload = {
            'amount': payment_utils.to_minor_currency_units(self.amount, self.currency_id),
        }
        _logger.info(
            "Sending '/orders/<id>/capture' request for transaction with reference %s:\n%s",
            self.reference, pprint.pformat(payload)
        )
        order_data = self.provider_id._revolut_make_request(
            f'orders/{self.provider_reference}/capture', payload=payload
        )
        _logger.info(
            "Response of '/orders/<id>/capture' request for transaction with reference %s:\n%s",
            self.reference, pprint.pformat(order_data)
        )
        self._handle_notification_data('revolut', {
            'order_id': self.provider_reference, 'order_data': order_data
        })
        return child_capture_tx

    def _send_void_request(self, amount_to_void=None):
        """ Override of `payment` to send a cancellation request to Revolut. """
        child_void_tx = super()._send_void_request(amount_to_void=amount_to_void)
        if self.provider_code != 'revolut':
            return child_void_tx

        _logger.info(
            "Sending '/orders/<id>/cancel' request for transaction with reference %s",
            self.reference
        )
        order_data = self.provider_id._revolut_make_request(
            f'orders/{self.provider_reference}/cancel'
        )
        _logger.info(
            "Response of '/orders/<id>/cancel' request for transaction with reference %s:\n%s",
            self.reference, pprint.pformat(order_data)
        )
        self._handle_notification_data('revolut', {
            'order_id': self.provider_reference, 'order_data': order_data
        })
        return child_void_tx

    def action_revolut_cancel_order(self):
        """ Cancel the order of a payment the customer started on the hosted page but never made.

        A pending transaction hides the portal 'Pay now' button of its invoice
        (`account.move._has_to_be_paid`), so an abandoned checkout locks the customer out of paying
        that invoice online. `const.ORDER_EXPIRE_PENDING_AFTER` closes that on its own, but only
        for orders created with it: an order from before that, or one whose window has not elapsed
        yet, needs a human to release it. This is that way out.

        The cancellation goes through `_send_void_request`, which is already the single place that
        calls the cancel endpoint and applies what comes back.

        :return: None
        :raise ValidationError: If any transaction is not a pending Revolut transaction.
        """
        payment_utils.check_rights_on_recordset(self)

        if any(tx.provider_code != 'revolut' or tx.state != 'pending' for tx in self):
            raise ValidationError("Revolut: " + _(
                "Only a pending Revolut transaction can be canceled here. A transaction that is "
                "done, authorized or already canceled must not have its order canceled behind "
                "Odoo's back."
            ))
        for tx in self:
            _logger.info(
                "Canceling the abandoned Revolut order %s of the transaction with reference %s.",
                tx.provider_reference, tx.reference
            )
            # In sudo mode to read the fields of the provider, as `action_void` does.
            tx.sudo()._send_void_request()

    def _send_refund_request(self, amount_to_refund=None):
        """ Override of `payment` to send a refund request to Revolut.

        Note: `self.ensure_one()`

        :param float amount_to_refund: The amount to refund.
        :return: The refund transaction created to process the refund request.
        :rtype: recordset of `payment.transaction`
        """
        refund_tx = super()._send_refund_request(amount_to_refund=amount_to_refund)
        if self.provider_code != 'revolut':
            return refund_tx

        payload = {  # The amount of a refund transaction is negative.
            'amount': payment_utils.to_minor_currency_units(
                -refund_tx.amount, refund_tx.currency_id
            ),
            'currency': refund_tx.currency_id.name,
            'description': refund_tx.reference,
        }
        _logger.info(
            "Sending '/orders/<id>/refund' request for transaction with reference %s:\n%s",
            self.reference, pprint.pformat(payload)
        )
        refund_data = self.provider_id._revolut_make_request(
            f'orders/{self.provider_reference}/refund', payload=payload
        )
        _logger.info(
            "Response of '/orders/<id>/refund' request for transaction with reference %s:\n%s",
            self.reference, pprint.pformat(refund_data)
        )
        # Revolut answers with an order of its own for the refund; it is that order, not the
        # original one, that later events are about.
        refund_tx.provider_reference = refund_data.get('id') or self.provider_reference
        refund_tx._handle_notification_data('revolut', {
            'order_id': refund_tx.provider_reference, 'order_data': refund_data
        })
        return refund_tx

    # === BUSINESS METHODS - POST-PROCESSING === #

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        """ Override of `payment` to find the transaction based on Revolut data.

        :param str provider_code: The code of the provider that handled the transaction.
        :param dict notification_data: The normalized notification data sent by the provider.
        :return: The transaction if found.
        :rtype: recordset of `payment.transaction`
        :raise ValidationError: If the data match no transaction.
        """
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != 'revolut' or len(tx) == 1:
            return tx

        # The order id is matched first, and the reference only as a fallback: a refund has an
        # order of its own but keeps the reference of the payment it refunds, so matching on the
        # reference alone would route a refund event to the original transaction.
        order_id = notification_data.get('order_id')
        reference = notification_data.get('reference')
        if order_id:
            tx = self.search(
                [('provider_reference', '=', order_id), ('provider_code', '=', 'revolut')], limit=1
            )
        if not tx and reference:
            tx = self.search(
                [('reference', '=', reference), ('provider_code', '=', 'revolut')], limit=1
            )
        if not tx:
            raise ValidationError("Revolut: " + _(
                "No transaction found matching the order %(order_id)s nor the reference "
                "%(ref)s. If this database shares a Revolut merchant account with another one, "
                "the notification is most likely about a transaction of that other database.",
                order_id=order_id or _("(none)"), ref=reference or _("(none)"),
            ))
        return tx

    def _process_notification_data(self, notification_data):
        """ Override of `payment` to process the transaction based on Revolut data.

        Note: `self.ensure_one()`

        :param dict notification_data: The notification data sent by the provider.
        :return: None
        :raise ValidationError: If inconsistent data were received.
        """
        super()._process_notification_data(notification_data)
        if self.provider_code != 'revolut':
            return

        self._revolut_verify_and_apply(
            order_data=notification_data.get('order_data'),  # Set by the requests made by Odoo.
            order_id=notification_data.get('order_id'),
        )

    def _revolut_verify_and_apply(self, order_data=None, order_id=None):
        """ Let an order decide the state of this transaction, once it is proven to be its order.

        This is the single place where a Revolut order changes anything about a transaction: the
        webhook, the customer coming back from the hosted page, the reconciliation cron and the
        capture / void / refund requests all end up here. Anything that skips it changes money
        without checking it.

        A notification only says *that* something happened, so the order is (re)fetched from the
        API unless the data come from a request Odoo itself made: the state acted upon is always
        Revolut's own, never a payload someone could have crafted.

        Note: `self.ensure_one()`

        :param dict order_data: The order data, when they come from a request Odoo made itself.
        :param str order_id: The id of the order to fetch, when it is not this transaction's own.
        :return: None
        :raise ValidationError: If the order cannot be fetched or does not match this transaction.
        """
        self.ensure_one()

        if not order_data:
            order_id = order_id or self.provider_reference
            if not order_id:
                raise ValidationError("Revolut: " + _(
                    "Received data with missing order id for the transaction %s, which has no "
                    "order id of its own either. There is nothing to ask Revolut about.",
                    self.reference
                ))
            order_data = self.provider_id._revolut_make_request(f'orders/{order_id}', method='GET')
            _logger.info(
                "Response of '/orders/<id>' request for transaction with reference %s:\n%s",
                self.reference, pprint.pformat(order_data)
            )

        self._revolut_check_order_matches(order_data)

        if not self.provider_reference and order_data.get('id'):
            self.provider_reference = order_data['id']

        self._revolut_update_payment_method(order_data)
        self._revolut_apply_order_state(order_data)

    def _revolut_check_order_matches(self, order_data):
        """ Refuse to act on an order that is not, to the cent, the order of this transaction.

        The state comes from the API and can be trusted; that it is the state of *this* payment
        cannot, and a wrong match is money in the wrong place: an order id that belongs to another
        transaction, an amount that drifted from the invoice, a currency that is not the one the
        customer agreed to. None of it should ever happen, which is exactly why it is checked
        rather than assumed — and why nothing is applied when it does.

        Amounts are compared in minor units, as integers: that is the number Revolut charged, and
        it is free of the rounding a float comparison would have to tolerate.

        Note: `self.ensure_one()`

        :param dict order_data: The order data fetched from Revolut.
        :return: None
        :raise ValidationError: If the order does not match this transaction.
        """
        self.ensure_one()

        mismatches = []
        order_id = order_data.get('id')
        if order_id and self.provider_reference and order_id != self.provider_reference:
            mismatches.append(
                f"the order id is {order_id}, but this transaction is about "
                f"{self.provider_reference}"
            )

        currency = order_data.get('currency')
        if currency and currency != self.currency_id.name:
            mismatches.append(
                f"the order is in {currency}, but this transaction is in {self.currency_id.name}"
            )

        order_amount = order_data.get('amount')
        # A refund is negative in Odoo and positive on the refund order Revolut answers with.
        expected_amount = payment_utils.to_minor_currency_units(
            abs(self.amount), self.currency_id
        )
        if order_amount is not None and int(order_amount) != expected_amount:
            mismatches.append(
                f"the order is for {order_amount} minor units, but this transaction is for "
                f"{expected_amount}"
            )

        if not mismatches:
            return

        _logger.warning(
            "Refused to apply the order %s to the transaction with reference %s: %s. Nothing was "
            "changed and no payment was posted. Either the order belongs to another transaction, "
            "or the amount of the transaction was altered after the order was created; both need a "
            "human before this payment can be confirmed.",
            order_id or "(unknown)", self.reference, '; '.join(mismatches)
        )
        self._revolut_alert(
            summary=_("Revolut payment does not match this document"),
            note=_(
                "Revolut returned an order that does not match the transaction %(reference)s, so "
                "nothing was confirmed and no payment was posted:%(mismatches)s Check the payment "
                "in the Revolut portal before confirming anything by hand.",
                reference=self.reference,
                mismatches=''.join(f"<br/>- {mismatch}" for mismatch in mismatches),
            ),
        )
        raise ValidationError("Revolut: " + _(
            "The order received for the transaction %(reference)s does not match it (%(reasons)s), "
            "so its state was left untouched.",
            reference=self.reference, reasons='; '.join(mismatches),
        ))

    def _revolut_apply_order_state(self, order_data):
        """ Move the transaction to the state the order is in.

        Note: `self.ensure_one()`

        :param dict order_data: The order data fetched from Revolut.
        :return: None
        :raise ValidationError: If the order carries no state.
        """
        self.ensure_one()

        order_state = order_data.get('state')
        if not order_state:
            raise ValidationError("Revolut: " + _(
                "Received data with missing state for the order %(order_id)s of the transaction "
                "%(reference)s. Its state cannot be guessed, so nothing is changed.",
                order_id=order_data.get('id') or _("(unknown)"), reference=self.reference,
            ))

        if order_state in const.PAYMENT_STATUS_MAPPING['pending']:
            # A `pending` order whose last attempt was refused is not a payment on its way: the
            # customer's card was declined and Revolut is only keeping the page open for a retry.
            # Telling them "your payment is being processed" would hide that, and would leave the
            # invoice waiting for money that was never taken.
            declined_payment = self._revolut_get_failed_payment(order_data)
            if declined_payment:
                _logger.info(
                    "The last payment on the order %s of the transaction with reference %s was "
                    "%s (%s); the order stays open for a retry, but the transaction is set in "
                    "error so that the customer is told.",
                    order_data.get('id'), self.reference, declined_payment.get('state'),
                    declined_payment.get('decline_reason') or "no reason given"
                )
                self._set_error(
                    _("Your payment was refused. Please try again or use another card.")
                )
            else:
                self._set_pending()
        elif order_state == 'authorised':
            # `authorised` means the money is reserved. With automatic capture, Revolut captures it
            # on its own and a `completed` event follows, so the transaction is only held pending.
            if self.provider_id.capture_manually:
                self._set_authorized()
            else:
                self._set_pending()
        elif order_state in const.PAYMENT_STATUS_MAPPING['done']:
            self._set_done()
            if self.operation == 'refund':
                # Nobody is browsing the portal after a refund, so post-processing (which posts the
                # payment in accounting) has to be triggered explicitly.
                self.env.ref('payment.cron_post_process_payment_tx')._trigger()
        elif order_state in const.PAYMENT_STATUS_MAPPING['cancel']:
            self._set_canceled()
        elif order_state in const.PAYMENT_STATUS_MAPPING['error']:
            if not (order_data.get('payments') or []):
                # The order died without anyone ever paying: it expired, or the customer never came
                # back. Nothing failed, so this is a cancellation, not an error to investigate.
                _logger.info(
                    "The order %s of the transaction with reference %s expired without a single "
                    "payment attempt; the transaction is canceled.",
                    order_data.get('id'), self.reference
                )
                self._set_canceled(state_message=_(
                    "The payment was never completed and the Revolut order expired."
                ))
            else:
                _logger.warning(
                    "The order %s of the transaction with reference %s is in the state '%s' on "
                    "Revolut: the payment did not go through. The customer has to try again.",
                    order_data.get('id'), self.reference, order_state
                )
                self._set_error(
                    _("An error occurred during the processing of your payment. Please try again.")
                )
        else:
            known_states = sorted(
                {'authorised', *(s for states in const.PAYMENT_STATUS_MAPPING.values()
                                 for s in states)}
            )
            _logger.warning(
                "Received the order %s of the transaction with reference %s in the unknown state "
                "'%s'; the transaction is set in error rather than left hanging. The states this "
                "module knows are: %s. A new state in the Merchant API means `const.py` has to be "
                "updated.",
                order_data.get('id'), self.reference, order_state, ', '.join(known_states)
            )
            self._set_error(
                "Revolut: " + _("Received data with invalid state: %s", order_state)
            )

    @staticmethod
    def _revolut_get_failed_payment(order_data):
        """ Return the last payment attempt of the order, if it is one that did not go through.

        Only the last attempt matters: an earlier decline followed by a successful retry is a paid
        order, not a failed one.

        :param dict order_data: The order data fetched from Revolut.
        :return: The failed payment attempt, if the last one failed.
        :rtype: dict
        """
        payments = order_data.get('payments') or []
        if not payments:
            return {}
        last_payment = payments[-1]
        if last_payment.get('state') in const.FAILED_PAYMENT_STATES:
            return last_payment
        return {}

    def _revolut_update_payment_method(self, order_data):
        """ Set the payment method actually used by the customer, when Revolut discloses it.

        The method is only known once a payment attempt exists on the order, so this is a
        best-effort update: an order that has not been paid yet keeps the method Odoo assumed.

        :param dict order_data: The order data fetched from Revolut.
        :return: None
        """
        payments = order_data.get('payments') or []
        if not payments:
            return

        payment_data = payments[-1]
        payment_method_data = payment_data.get('payment_method') or {}
        method_code = payment_method_data.get('type')
        if method_code == 'card':  # Prefer the brand ("visa") over the generic "card".
            method_code = (
                payment_method_data.get('card_brand')
                or payment_method_data.get('brand')
                or method_code
            )
        if not method_code:
            return

        payment_method = self.env['payment.method']._get_from_code(
            method_code.lower(), mapping=const.PAYMENT_METHODS_MAPPING
        )
        if not payment_method:
            _logger.info(
                "Revolut reported that the transaction with reference %s was paid with '%s', which "
                "matches no active payment method in Odoo; keeping '%s'. Activate that payment "
                "method, or map it in `const.PAYMENT_METHODS_MAPPING`, to see it on the "
                "transaction.", self.reference, method_code, self.payment_method_id.code
            )
        self.payment_method_id = payment_method or self.payment_method_id
