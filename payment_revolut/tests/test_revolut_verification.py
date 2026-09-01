from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment_revolut.tests.common import RevolutCommon

_TRANSACTION_LOGGER = 'odoo.addons.payment_revolut.models.payment_transaction'


@tagged('post_install', '-at_install')
class RevolutVerificationTest(RevolutCommon):
    """ What has to be true about an order before it is allowed to decide anything.

    The state of an order can be trusted: it is read from the API, not from a payload. That it is
    the state of *this* transaction cannot, and getting that wrong is money in the wrong place.
    """

    def _apply(self, tx, **order_values):
        """ Apply an order to a transaction, as the webhook and the cron both end up doing. """
        tx._revolut_verify_and_apply(order_data=self._revolut_order(**order_values))

    # === The order must be this transaction's order === #

    @mute_logger(_TRANSACTION_LOGGER)
    def test_a_smaller_amount_is_refused(self):
        tx = self._create_transaction(flow='redirect', provider_reference=self.order_id)

        with self.assertRaises(ValidationError):
            self._apply(tx, state='completed', amount=100)

        self.assertTxState(tx, 'draft', why=(
            "An order for less money than the transaction must change nothing. Confirming it would "
            "post a payment for an amount the customer never paid, and close an invoice that is "
            "still owed."
        ))

    @mute_logger(_TRANSACTION_LOGGER)
    def test_a_larger_amount_is_refused(self):
        tx = self._create_transaction(flow='redirect', provider_reference=self.order_id)

        with self.assertRaises(ValidationError):
            self._apply(tx, state='completed', amount=999999)

        self.assertTxState(tx, 'draft', why=(
            "An order for more money than the transaction must change nothing: the customer was "
            "charged something nobody in Odoo agreed to, and that needs a human, not a confirmed "
            "payment."
        ))

    @mute_logger(_TRANSACTION_LOGGER)
    def test_another_currency_is_refused(self):
        tx = self._create_transaction(flow='redirect', provider_reference=self.order_id)

        with self.assertRaises(ValidationError):
            self._apply(tx, state='completed', currency='USD')

        self.assertTxState(tx, 'draft', why=(
            "The same number in another currency is not the same money. An order in a currency "
            "the transaction is not in must never confirm it."
        ))

    @mute_logger(_TRANSACTION_LOGGER)
    def test_a_mismatch_is_refused_before_anything_is_written(self):
        """ The refusal has to come first, or half of the transaction is updated from a stranger's
        order. """
        tx = self._create_transaction(flow='redirect', provider_reference=self.order_id)
        method_before = tx.payment_method_id

        with self.assertRaises(ValidationError):
            self._apply(tx, state='completed', amount=100, payments=[
                {'payment_method': {'type': 'card', 'card_brand': 'visa'}},
            ])

        self.assertEqual(tx.payment_method_id, method_before, msg=(
            "Nothing from a mismatching order may be written on the transaction, not even the "
            "payment method: data that cannot be trusted to set the state cannot be trusted to "
            "set anything else either."
        ))

    def test_the_expected_amount_confirms_the_transaction(self):
        """ The check must not stand in the way of the ordinary case. """
        tx = self._create_transaction(flow='redirect', provider_reference=self.order_id)

        self._apply(tx, state='completed')

        self.assertTxState(tx, 'done', why=(
            "An order that matches the transaction to the cent must confirm it. If this fails, no "
            "payment can ever be confirmed."
        ))

    # === Minor units, where currencies stop agreeing with each other === #

    def test_a_zero_decimal_currency_is_compared_in_its_own_units(self):
        """ ¥1,000 is 1000 minor units, not 100000.

        Revolut counts minor units as ISO 4217 does, and so does Odoo. A comparison that assumed
        two decimals would refuse every correct payment in a zero-decimal currency, and accept one
        that is a hundred times too small.
        """
        jpy = self.env.ref('base.JPY')
        jpy.active = True
        tx = self._create_transaction(
            flow='redirect', provider_reference=self.order_id,
            amount=1000.0, currency_id=jpy.id,
        )

        self._apply(tx, state='completed', amount=1000, currency='JPY')

        self.assertTxState(tx, 'done', why=(
            "1000 JPY is 1000 minor units. Comparing it as if the yen had cents would leave every "
            "Japanese payment unconfirmed."
        ))

    @mute_logger(_TRANSACTION_LOGGER)
    def test_a_zero_decimal_amount_off_by_a_factor_is_refused(self):
        jpy = self.env.ref('base.JPY')
        jpy.active = True
        tx = self._create_transaction(
            flow='redirect', provider_reference=self.order_id,
            amount=1000.0, currency_id=jpy.id,
        )

        with self.assertRaises(ValidationError):
            self._apply(tx, state='completed', amount=100000, currency='JPY')

        self.assertTxState(tx, 'draft', why=(
            "An order for ¥100,000 must not confirm a transaction for ¥1,000, however plausible "
            "the number looks next to a two-decimal currency."
        ))

    def test_the_amount_is_compared_the_way_it_was_sent(self):
        """ Whatever rounding the currency imposes, both sides must be rounded the same way.

        The order was created from `to_minor_currency_units`, so the check has to compare against
        that same number — not against the float the transaction carries.
        """
        tx = self._create_transaction(flow='redirect', provider_reference=self.order_id)
        sent_amount = payment_utils.to_minor_currency_units(tx.amount, tx.currency_id)

        self._apply(tx, state='completed', amount=sent_amount)

        self.assertTxState(tx, 'done', why=(
            "The amount checked must be the amount that was sent to Revolut. Any other rounding "
            "makes the check disagree with the order it is checking."
        ))

    def test_a_refund_is_compared_on_its_own_amount(self):
        """ A refund is negative in Odoo and positive on the order Revolut answers with. """
        tx = self._create_transaction(
            flow='redirect', provider_reference=self.order_id, state='done'
        )
        refund_tx = tx._create_child_transaction(100.0, is_refund=True)
        refund_tx.provider_reference = self.refund_order_id

        refund_tx._revolut_verify_and_apply(order_data={
            'id': self.refund_order_id, 'state': 'completed', 'amount': 10000, 'currency': 'EUR',
        })

        self.assertTxState(refund_tx, 'done', why=(
            "A refund order carries the refunded amount as a positive number, while Odoo stores "
            "the refund as negative. Comparing the signs instead of the amounts would refuse every "
            "refund Revolut confirms."
        ))
