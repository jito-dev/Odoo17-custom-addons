from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment_revolut import const
from odoo.addons.payment_revolut.tests.common import REQUEST_PATH, RevolutCommon

_TRANSACTION_LOGGER = 'odoo.addons.payment_revolut.models.payment_transaction'
_RECONCILE_LOGGER = 'odoo.addons.payment_revolut.models.payment_transaction_reconcile'
_PROVIDER_LOGGER = 'odoo.addons.payment_revolut.models.payment_provider'


@tagged('post_install', '-at_install')
class RevolutReconcileTest(RevolutCommon):
    """ The safety net: Revolut gives up on a webhook after four attempts, Odoo does not.

    Everything here answers the same question — what happens to a payment nobody told Odoo about.
    """

    def _create_stale_transaction(self, age_minutes=30, **values):
        """ Return a transaction that has been waiting long enough to be worth asking about. """
        tx = self._create_transaction(
            flow='redirect', provider_reference=self.order_id, **values
        )
        stale_date = fields.Datetime.now() - timedelta(minutes=age_minutes)
        # `create_date` is one of the log-access columns the ORM refuses to write, and the age of a
        # transaction is exactly what decides whether it is polled: a test that cannot age one
        # tests nothing.
        self.env.cr.execute(
            "UPDATE payment_transaction SET create_date = %s WHERE id = %s", (stale_date, tx.id)
        )
        tx.invalidate_recordset(['create_date'])
        tx.last_state_change = stale_date
        return tx

    # === How long one run may take === #

    def test_a_run_stops_when_it_is_out_of_time(self):
        """ The budget is what keeps one unreachable host from holding a cron worker for an hour. """
        first, second = (self._create_stale_transaction(reference=f'BUDGET-{i}') for i in range(2))
        (first + second)._set_pending()
        # Time jumps past the budget after the first transaction has been polled.
        clock = iter([0, 0, const.CRON_TIME_BUDGET_SECONDS + 1])
        with patch(REQUEST_PATH, return_value=self._revolut_order(state='completed')) as api, \
                patch(
                    'odoo.addons.payment_revolut.models.payment_transaction_reconcile.time.'
                    'monotonic', side_effect=lambda: next(clock, 10 ** 9)
                ):
            self.env['payment.transaction']._cron_revolut_reconcile_pending_transactions()
        self.assertEqual(len(api.mock_calls), 1, msg=(
            "A run that is out of budget must stop, not finish the batch. Without this the cron "
            "walks up to a hundred transactions against an API with a 60-second timeout, and "
            "every other cron waits behind it.\n"
            f"    API calls made: {len(api.mock_calls)} (expected 1: one before the clock jumped)"
        ))
        self.assertTxState(first, 'done', (
            "What the run did manage to poll before running out of time must be kept — the "
            "budget postpones work, it does not discard it."
        ))
        self.assertTxState(second, 'pending', (
            "The transaction left over must stay untouched, so the next run picks it up. Marking "
            "it in any way would hide that it was never actually asked about."
        ))

    # === Which transactions are asked about === #

    def test_a_pending_transaction_is_reconciled(self):
        tx = self._create_stale_transaction()
        tx._set_pending()

        with patch(REQUEST_PATH, return_value=self._revolut_order(state='completed')) as api:
            self.env['payment.transaction']._cron_revolut_reconcile_pending_transactions()

        self.assertApiCalls(api, [((f'orders/{self.order_id}',), {'method': 'GET'})], why=(
            "A transaction that never reached a final state must be asked about. Revolut retries a "
            "webhook four times and then forgets it: without this query, that payment is lost for "
            "good."
        ))
        self.assertTxState(tx, 'done', why=(
            "The state fetched from the API must be applied. Fetching it and doing nothing with it "
            "leaves the invoice open next to a paid order."
        ))

    def test_a_transaction_too_young_is_left_alone(self):
        tx = self._create_stale_transaction(age_minutes=0)
        tx._set_pending()

        with patch(REQUEST_PATH) as api:
            self.env['payment.transaction']._cron_revolut_reconcile_pending_transactions()

        self.assertNoApiCall(api, why=(
            "A transaction created seconds ago must not be polled: the customer is still on the "
            "hosted page, and the API would be asked about an order nobody has opened yet."
        ))

    def test_a_transaction_older_than_the_window_is_left_alone(self):
        tx = self._create_stale_transaction(
            age_minutes=(const.POLL_MAX_AGE_DAYS * 24 * 60) + 60
        )
        tx._set_pending()

        with patch(REQUEST_PATH) as api:
            self.env['payment.transaction']._cron_revolut_reconcile_pending_transactions()

        self.assertNoApiCall(api, why=(
            "An order that outlived the longest possible order must stop being polled, or every "
            "abandoned checkout is queried forever, several times an hour, for nothing."
        ))

    def test_a_finished_transaction_is_left_alone(self):
        tx = self._create_stale_transaction()
        tx._set_done()

        with patch(REQUEST_PATH) as api:
            self.env['payment.transaction']._cron_revolut_reconcile_pending_transactions()

        self.assertNoApiCall(api, why=(
            "A transaction that already reached a final state has nothing left to reconcile."
        ))

    def test_transactions_of_other_providers_are_left_alone(self):
        tx = self._create_stale_transaction()
        tx._set_pending()
        tx.provider_id = self.env['payment.provider'].search([('code', '!=', 'revolut')], limit=1)

        with patch(REQUEST_PATH) as api:
            self.env['payment.transaction']._cron_revolut_reconcile_pending_transactions()

        self.assertNoApiCall(api, why=(
            "This job speaks only for Revolut. Reaching for another provider's transactions would "
            "ask Revolut about orders it has never heard of."
        ))

    def test_nothing_is_polled_without_a_usable_provider(self):
        tx = self._create_stale_transaction()
        tx._set_pending()
        self.provider.state = 'disabled'

        with patch(REQUEST_PATH) as api:
            self.env['payment.transaction']._cron_revolut_reconcile_pending_transactions()

        self.assertNoApiCall(api, why=(
            "A database that does not take Revolut payments must not pay for this job: it has to "
            "cost one query and stop."
        ))

    # === One failure must not cost the others === #

    @mute_logger(_TRANSACTION_LOGGER, _RECONCILE_LOGGER, _PROVIDER_LOGGER)
    def test_a_failing_transaction_does_not_stop_the_run(self):
        """ Each transaction is committed on its own, so the run survives a bad one. """
        first = self._create_stale_transaction(age_minutes=60, reference='REV-FIRST')
        first._set_pending()
        second = self._create_stale_transaction(age_minutes=30, reference='REV-SECOND')
        second._set_pending()
        second.provider_reference = 'another-order-id'

        def _fail_then_succeed(endpoint, *args, **kwargs):
            if endpoint.endswith(self.order_id):
                raise ValidationError("Revolut: the API is unreachable")
            return self._revolut_order(id='another-order-id', state='completed')

        with patch(REQUEST_PATH, side_effect=_fail_then_succeed):
            self.env['payment.transaction']._cron_revolut_reconcile_pending_transactions()

        self.assertTxState(second, 'done', why=(
            "One transaction Revolut cannot answer about must not cost every transaction after it. "
            "A run that stops at the first error reconciles nothing on the day it matters most."
        ))
        self.assertTxState(first, 'pending', why=(
            "The transaction that could not be reconciled must keep its state and be picked up "
            "again by the next run."
        ))

    # === Telling a human === #

    @mute_logger(_TRANSACTION_LOGGER, _RECONCILE_LOGGER, _PROVIDER_LOGGER)
    def test_a_payment_pending_for_too_long_alerts_the_responsible(self):
        self.provider.revolut_alert_user_id = self.env.user
        tx = self._create_stale_transaction(
            age_minutes=(const.STUCK_ALERT_DELAY_HOURS * 60) + 30
        )
        tx._set_pending()
        tx.write({'last_state_change': fields.Datetime.now() - timedelta(
            hours=const.STUCK_ALERT_DELAY_HOURS, minutes=30
        )})

        with patch(REQUEST_PATH, return_value=self._revolut_order(state='pending')):
            self.env['payment.transaction']._cron_revolut_reconcile_pending_transactions()

        self.assertTrue(tx.revolut_alert_sent, msg=(
            "A payment still pending an hour later is either money nobody sent or notifications "
            "that never arrive. Both need a human, and nothing else in Odoo says so.\n"
            f"    transaction: {tx.reference} ({tx.state})"
        ))

    @mute_logger(_TRANSACTION_LOGGER, _RECONCILE_LOGGER, _PROVIDER_LOGGER)
    def test_the_same_payment_is_not_alerted_twice(self):
        """ The job comes back every fifteen minutes; the alert must not. """
        self.provider.revolut_alert_user_id = self.env.user
        tx = self._create_stale_transaction(
            age_minutes=(const.STUCK_ALERT_DELAY_HOURS * 60) + 30
        )
        tx._set_pending()
        tx.write({'last_state_change': fields.Datetime.now() - timedelta(
            hours=const.STUCK_ALERT_DELAY_HOURS, minutes=30
        )})

        messages_before = self.env['mail.message'].search_count([])
        with patch(REQUEST_PATH, return_value=self._revolut_order(state='pending')):
            for _run in range(3):
                self.env['payment.transaction']._cron_revolut_reconcile_pending_transactions()
        raised = self.env['mail.message'].search_count([]) - messages_before

        self.assertEqual(raised, 1, msg=(
            "Ninety-six identical alerts a day are ninety-six alerts nobody reads. One "
            "transaction that needs attention must produce exactly one alert.\n"
            f"    alerts raised over three runs: {raised}"
        ))

    def test_a_payment_pending_for_a_moment_is_not_alerted(self):
        self.provider.revolut_alert_user_id = self.env.user
        tx = self._create_stale_transaction(age_minutes=5)
        tx._set_pending()

        with patch(REQUEST_PATH, return_value=self._revolut_order(state='pending')):
            self.env['payment.transaction']._cron_revolut_reconcile_pending_transactions()

        self.assertFalse(tx.revolut_alert_sent, msg=(
            "A payment pending for five minutes is a payment in progress. Alerting on it teaches "
            "whoever receives the alerts to ignore them."
        ))

    @mute_logger(_TRANSACTION_LOGGER, _RECONCILE_LOGGER, _PROVIDER_LOGGER)
    def test_an_amount_mismatch_alerts_the_responsible(self):
        """ The one case where the module refuses to act: somebody has to hear about it. """
        self.provider.revolut_alert_user_id = self.env.user
        tx = self._create_stale_transaction()
        tx._set_pending()

        with patch(REQUEST_PATH, return_value=self._revolut_order(state='completed', amount=1)):
            self.env['payment.transaction']._cron_revolut_reconcile_pending_transactions()

        self.assertTrue(tx.revolut_alert_sent, msg=(
            "An order whose amount does not match the transaction is refused — and a refusal "
            "nobody is told about is a payment silently stuck forever."
        ))
        self.assertTxState(tx, 'pending', why=(
            "The refused order must leave the state untouched, even when the refusal is raised "
            "from a background job."
        ))

    @mute_logger(_TRANSACTION_LOGGER, _RECONCILE_LOGGER, _PROVIDER_LOGGER)
    def test_the_alert_lands_on_the_document_the_payment_is_for(self):
        """ An activity on the invoice, because that is the document the accountant opens.

        A log line is read by whoever is already looking; an activity is what makes somebody look.
        """
        if 'invoice_ids' not in self.env['payment.transaction']._fields:
            self.skipTest("Invoicing is not installed in this database.")
        self.provider.revolut_alert_user_id = self.env.user
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_line_ids': [(0, 0, {'name': "Test", 'quantity': 1, 'price_unit': self.amount})],
        })
        tx = self._create_stale_transaction()
        tx._set_pending()
        tx.invoice_ids = [(4, invoice.id)]

        with patch(REQUEST_PATH, return_value=self._revolut_order(state='completed', amount=1)):
            self.env['payment.transaction']._cron_revolut_reconcile_pending_transactions()

        activity = invoice.activity_ids.filtered(lambda a: a.user_id == self.env.user)
        self.assertTrue(activity, msg=(
            "The alert must land on the invoice the payment is for, as an activity for the "
            "responsible. Anywhere else and the person who has to act on it never sees it.\n"
            f"    activities on the invoice: {invoice.activity_ids.mapped('summary') or '(none)'}"
        ))

    # === Who is told === #

    def test_the_configured_responsible_is_used(self):
        self.provider.revolut_alert_user_id = self.env.user
        self.assertEqual(self.provider._revolut_get_alert_user(), self.env.user, msg=(
            "The responsible set on the provider must be the one who is told. Anything else makes "
            "the field a decoration."
        ))

    @mute_logger(_PROVIDER_LOGGER)
    def test_an_unset_responsible_falls_back_to_an_accountant(self):
        accountants = self.env.ref('account.group_account_manager', raise_if_not_found=False)
        if not accountants:
            self.skipTest("Accounting is not installed in this database.")
        self.provider.revolut_alert_user_id = False

        user = self.provider._revolut_get_alert_user()

        self.assertIn(user, accountants.users, msg=(
            "With no responsible configured, the alert must still reach an accountant rather than "
            "disappear: a misconfigured field is not a reason to lose a payment."
        ))
