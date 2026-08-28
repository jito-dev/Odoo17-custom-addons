import logging
import time

import psycopg2

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models, modules, tools
from odoo.exceptions import ValidationError

from odoo.addons.payment_revolut import const

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    """ Making sure a payment cannot be lost, and that a human hears about it when it is stuck.

    Revolut retries a webhook it could not deliver three times, ten minutes apart, and then drops
    it for good. A database that is unreachable for an hour — a deploy, a restart, an expired
    certificate — never hears about those payments again: the money is taken, the invoice stays
    open, and nothing in Odoo says so. The reconciliation cron below is what closes that hole, by
    asking the API instead of waiting to be told.
    """
    _inherit = 'payment.transaction'

    revolut_alert_sent = fields.Boolean(
        string="Revolut Alert Raised",
        help="Whether somebody was already told that this transaction needs a human. Keeps a "
             "recurring check from raising the same alert every fifteen minutes.",
        copy=False,
        readonly=True,
    )
    revolut_last_poll = fields.Datetime(
        string="Revolut Last Polled",
        help="When Revolut was last asked about this transaction from the payment status page. "
             "Keeps the customer's browser, which polls every three seconds, from turning one "
             "payment into a dozen API calls.",
        copy=False,
        readonly=True,
    )

    # === BUSINESS METHODS - STATUS PAGE === #

    def _get_post_processing_values(self):
        """ Override of `payment` to refresh a waiting Revolut transaction from the API.

        Revolut redirects the customer back as soon as the hosted page is done with them, which
        is regularly *before* the order leaves `processing` — verified on 2026-08-27, when the
        return route fetched an order five seconds after a successful 3DS payment and got
        `processing` with `authorisation_passed` on the attempt. Odoo then correctly records
        `pending`, and nothing revisits that until a webhook arrives or the reconciliation cron
        runs. With the webhook undelivered that is a fifteen-minute wait, during which the
        customer reads "your payment is waiting for approval" for money that already left their
        card.

        The status page is already polling this every three seconds while they wait
        (`payment/static/src/js/post_processing.js`), so the state is refreshed here, at the cost
        of one API call per `const.POLL_STATUS_MIN_INTERVAL_SECONDS`. The wait becomes about
        three seconds.

        This is not a replacement for the webhook: it only runs while somebody is watching the
        page. A customer who closes the tab is still covered by the cron alone.

        Note: `self.ensure_one()`
        """
        self._revolut_refresh_for_status_page()
        return super()._get_post_processing_values()

    def _revolut_refresh_for_status_page(self):
        """ Ask Revolut about this transaction, if it is one and it is worth asking about.

        Every failure is swallowed: this runs while a customer is looking at the status page, and
        an API that is slow, down or answering nonsense must never turn their page into an error.
        The state simply stays what it was, and the cron picks it up later — which is exactly what
        would have happened without this method.

        Note: `self.ensure_one()`

        :return: None
        """
        self.ensure_one()

        if self.provider_code != 'revolut' or self.state not in ('draft', 'pending'):
            return  # Nothing to refresh, or already in a state the page will act on.
        if not self.provider_reference:
            return  # The order was never created; there is nothing to ask about.

        now = fields.Datetime.now()
        if self.revolut_last_poll and (now - self.revolut_last_poll).total_seconds() < \
                const.POLL_STATUS_MIN_INTERVAL_SECONDS:
            return

        self.revolut_last_poll = now
        try:
            self._revolut_verify_and_apply()
        except Exception:  # noqa: BLE001 - the status page must render whatever happens.
            _logger.exception(
                "Could not refresh the transaction with reference %s from the payment status "
                "page; leaving its state untouched for the reconciliation cron.", self.reference
            )
            return

        # `PaymentPostProcessing.poll_status` decides whether to post-process *before* it asks for
        # these values, so a transaction that just became `done` here would otherwise wait for the
        # next poll — or, if the customer is redirected first, for the post-processing cron. Doing
        # it now is what makes the invoice closed by the time they land on it.
        if self.state == 'done' and not self.is_post_processed:
            try:
                self._finalize_post_processing()
            except Exception:  # noqa: BLE001
                _logger.exception(
                    "Could not post-process the transaction with reference %s right after it was "
                    "confirmed from the status page; the post-processing cron will retry.",
                    self.reference
                )

    # === BUSINESS METHODS - RECONCILIATION === #

    @api.model
    def _cron_revolut_reconcile_pending_transactions(self, batch_size=None):
        """ Ask Revolut about the transactions that never reached a final state.

        Each transaction is committed on its own, so that one unreachable order or one alert that
        cannot be raised does not undo the work done for the others.

        The run is bounded by `const.CRON_TIME_BUDGET_SECONDS` as well as by the batch size: it
        talks to an API with a 60-second timeout up to a hundred times, and a cron worker held for
        the better part of an hour would starve every other cron behind it. Whatever is left over
        is the newest of the batch and is picked up first next time.

        :param int batch_size: The maximum number of transactions to poll in this run.
        :return: None
        """
        usable_provider = self.env['payment.provider'].sudo().search_count(
            [('code', '=', 'revolut'), ('state', '!=', 'disabled')], limit=1
        )
        if not usable_provider:
            return  # Nothing to reconcile on a database that does not take Revolut payments.

        transactions = self._revolut_get_transactions_to_reconcile(batch_size=batch_size)
        if not transactions:
            return

        _logger.info(
            "Reconciling %s Revolut transaction(s) that have not reached a final state: %s",
            len(transactions), ', '.join(transactions.mapped('reference'))
        )
        deadline = time.monotonic() + const.CRON_TIME_BUDGET_SECONDS
        for index, tx in enumerate(transactions):
            if time.monotonic() > deadline:
                # Out of budget. What is kept has been committed one by one, and the transactions
                # left over are the newest of the batch, so the next run reaches them first.
                _logger.info(
                    "Stopping this reconciliation run after %ss: %s of %s transaction(s) were "
                    "polled, the remaining %s are left to the next run.",
                    const.CRON_TIME_BUDGET_SECONDS, index, len(transactions),
                    len(transactions) - index
                )
                break
            try:
                state_before = tx.state
                tx._revolut_verify_and_apply()
                tx._revolut_alert_if_stuck(state_before)
                self._revolut_commit()
            except ValidationError as error:
                # The order was fetched but could not be applied: it does not match this
                # transaction, or it carries a state this module does not know. Both raised an
                # alert of their own, and that alert is the whole point of the run — so the work
                # done so far is kept, not thrown away.
                _logger.warning(
                    "Could not reconcile the transaction with reference %s: %s",
                    tx.reference, error
                )
                self._revolut_commit()
            except psycopg2.OperationalError:
                self._revolut_rollback()  # A concurrency error; the next run tries again.
            except Exception:
                _logger.exception(
                    "Unexpected error while reconciling the transaction with reference %s; moving "
                    "on to the next one.", tx.reference
                )
                self._revolut_rollback()

    @api.model
    def _revolut_commit(self):
        """ Keep what has been reconciled so far, so that a later failure cannot undo it.

        A run walks through up to a hundred transactions and talks to an API in between; without
        committing, an error on the last one would throw away the ninety-nine payments confirmed
        before it. Committing is skipped while testing, where the whole run has to stay inside the
        test's own transaction — this is the same guard as `account.move._can_commit`.

        :return: None
        """
        if self._revolut_can_commit():
            self.env.cr.commit()

    @api.model
    def _revolut_rollback(self):
        """ Undo the half-done work of the transaction that just failed. See `_revolut_commit`. """
        if self._revolut_can_commit():
            self.env.cr.rollback()

    @staticmethod
    def _revolut_can_commit():
        """ Return whether this run may commit, which it may not while tests are running. """
        return not tools.config['test_enable'] and not modules.module.current_test

    @api.model
    def _revolut_get_transactions_to_reconcile(self, batch_size=None):
        """ Return the transactions worth asking Revolut about.

        A transaction is polled once the customer has had time to reach the hosted page, and until
        its order can no longer change on Revolut's side. Polling sooner would fetch orders nobody
        has opened yet; polling forever would keep asking about orders that expired long ago.

        :param int batch_size: The maximum number of transactions to return.
        :return: The transactions to reconcile, oldest first.
        :rtype: recordset of `payment.transaction`
        """
        now = fields.Datetime.now()
        return self.search(
            [
                ('provider_code', '=', 'revolut'),
                ('state', 'in', ('draft', 'pending', 'authorized')),
                ('provider_reference', '!=', False),
                ('create_date', '<=', now - relativedelta(minutes=const.POLL_MIN_AGE_MINUTES)),
                ('create_date', '>=', now - relativedelta(days=const.POLL_MAX_AGE_DAYS)),
            ],
            order='create_date asc',
            limit=batch_size or const.POLL_BATCH_SIZE,
        )

    def _revolut_alert_if_stuck(self, state_before):
        """ Tell a human about a payment that has been waiting for too long.

        A payment that is legitimately pending — a redirect, a slow issuer — settles in minutes.
        One that is still pending an hour later is not going to settle on its own: either the
        customer walked away, and the invoice is waiting for money nobody sent, or something is
        broken between Revolut and this database. Neither is visible from anywhere else.

        A transaction awaiting a manual capture is deliberately left alone: it is waiting for
        somebody in this company, not for Revolut.

        Note: `self.ensure_one()`

        :param str state_before: The state the transaction was in before it was reconciled.
        :return: None
        """
        self.ensure_one()

        if self.state not in ('draft', 'pending') or self.state != state_before:
            return  # It just moved, or it is waiting for a capture: nothing is stuck.

        stuck_since = self.last_state_change or self.create_date
        if not stuck_since:
            return
        alert_after = fields.Datetime.now() - relativedelta(hours=const.STUCK_ALERT_DELAY_HOURS)
        if stuck_since > alert_after:
            return  # Still within the window where waiting is normal.

        _logger.warning(
            "The transaction with reference %s has been %s since %s and Revolut still reports its "
            "order %s as unfinished. Either the customer never paid, or notifications are not "
            "reaching this database.",
            self.reference, self.state, stuck_since, self.provider_reference
        )
        self._revolut_alert(
            summary=_("Revolut payment still pending"),
            note=_(
                "The payment %(reference)s (%(amount)s %(currency)s) has been waiting since "
                "%(since)s and Revolut still reports its order as unfinished.<br/>"
                "Check the order %(order_id)s in the Revolut portal: if the customer never paid, "
                "this document is still unpaid; if they did, notifications are not reaching this "
                "database.",
                reference=self.reference,
                amount=self.amount,
                currency=self.currency_id.name,
                since=stuck_since,
                order_id=self.provider_reference or _("(none)"),
            ),
        )

    # === BUSINESS METHODS - ALERTS === #

    def _revolut_alert(self, summary, note):
        """ Put a payment that needs a human in front of one.

        The alert is an activity on the invoice or the order the payment is for, because that is
        the document the accountant is going to open anyway, and an activity has to be closed by
        hand — a log line does not. A payment with no document behind it (a bare payment link)
        falls back to a notification, which still reaches the same person's inbox.

        Only one alert is raised per transaction: the reconciliation cron comes back every fifteen
        minutes, and an alert repeated ninety-six times a day is an alert nobody reads.

        Note: `self.ensure_one()`

        :param str summary: The one-line summary of what needs attention.
        :param str note: The body of the alert, as HTML.
        :return: None
        """
        self.ensure_one()

        if self.revolut_alert_sent:
            _logger.info(
                "An alert was already raised for the transaction with reference %s; not raising "
                "another one for: %s", self.reference, summary
            )
            return

        user = self.provider_id._revolut_get_alert_user()
        if not user:
            return  # Why there is nobody to alert is logged by the provider.

        documents = self._revolut_get_alert_documents()
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if documents and activity_type:
            for records in documents:
                records.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=user.id,
                    summary=summary,
                    note=note,
                )
            document_names = [record.display_name for records in documents for record in records]
            _logger.info(
                "Raised an alert for the transaction with reference %s as an activity for %s on "
                "%s.", self.reference, user.display_name, ', '.join(document_names)
            )
        else:
            self.env['mail.thread'].message_notify(
                partner_ids=user.partner_id.ids,
                subject=summary,
                body=note,
                model=self._name,
                res_id=self.id,
            )
            _logger.info(
                "Raised an alert for the transaction with reference %s as a notification to %s: "
                "there is no document to hang an activity on.",
                self.reference, user.display_name
            )
        self.revolut_alert_sent = True

    def _revolut_get_alert_documents(self):
        """ Return the documents this payment is for, as a list of recordsets.

        A refund carries no document of its own; the document is the one the refunded payment was
        for. The fields themselves come from other modules (`account_payment`, `sale`), so each is
        looked up rather than assumed: this module depends on `payment` alone.

        Note: `self.ensure_one()`

        :return: The documents, one recordset per model.
        :rtype: list
        """
        self.ensure_one()

        tx = self.source_transaction_id or self
        documents = []
        for field_name in ('invoice_ids', 'sale_order_ids'):
            if field_name in tx._fields and tx[field_name]:
                documents.append(tx[field_name])
        return documents
