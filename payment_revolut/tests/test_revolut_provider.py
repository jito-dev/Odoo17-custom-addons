from unittest.mock import call, patch

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged

from odoo.addons.payment_revolut import const
from odoo.addons.payment_revolut.tests.common import REQUEST_PATH, RevolutCommon


@tagged('post_install', '-at_install')
class RevolutProviderTest(RevolutCommon):
    """ The provider itself: its configuration and the management of its webhook.

    The HTTP layer it talks through lives in `test_revolut_http.py`.
    """

    # === Configuration === #

    def test_api_url_follows_the_provider_state(self):
        """ Sandbox and production are separate installations, selected by the state. """
        for state, environment in (('test', 'sandbox'), ('enabled', 'production')):
            with self.subTest(provider_state=state):
                self.provider.state = state
                self.assertEqual(
                    self.provider._revolut_get_api_url(), const.API_URLS[environment],
                    msg=(
                        f"A provider in the state {state!r} must talk to the {environment} host. "
                        f"Nothing in the API key tells the two environments apart, so a wrong host "
                        f"here means real customers are charged on the sandbox, or test payments "
                        f"are charged for real."
                    ),
                )

    def test_feature_support_fields(self):
        """ Refunds are partial, captures are full-only; the views and wizards rely on this. """
        self.assertEqual(
            self.provider.support_refund, 'partial',
            msg=(
                "Revolut refunds any amount up to the captured total. Losing 'partial' hides the "
                "partial refund wizard from the transaction form."
            ),
        )
        self.assertEqual(
            self.provider.support_manual_capture, 'full_only',
            msg=(
                "Captures are deliberately full-only: 'partial' would offer a partial capture "
                "wizard whose child transactions Revolut does not model the same way."
            ),
        )

    def test_handled_webhook_events_cover_the_whole_payment_flow(self):
        """ Pin the event list itself: the test above only proves the payload is built from it.

        Each of these events answers a question Odoo cannot answer on its own, and the webhook has
        to be regenerated whenever the list changes.
        """
        self.assertEqual(
            set(const.HANDLED_WEBHOOK_EVENTS),
            {
                'ORDER_COMPLETED',  # The money is in: confirm the transaction.
                'ORDER_AUTHORISED',  # The money is reserved: a manual capture becomes possible.
                'ORDER_CANCELLED',  # The authorisation was released.
                'ORDER_FAILED',  # The order reached the end of its life, paid or not.
                'ORDER_PAYMENT_DECLINED',  # The bank refused the payment.
                'ORDER_PAYMENT_FAILED',  # The attempt broke down.
            },
            msg=(
                "Dropping an event stops Odoo from ever being told about that outcome — a "
                "transaction then waits forever for a notification that is no longer sent. Adding "
                "one that Revolut does not know makes the whole webhook creation fail. Whoever "
                "changes this list must also press 'Generate your webhook' on every database, "
                "since the subscription lives on Revolut's side.\n"
                f"    currently handled: {sorted(const.HANDLED_WEBHOOK_EVENTS)}"
            ),
        )

    def test_payout_events_are_not_handled(self):
        """ Payouts are settlements to the merchant's own account, not customer payments. """
        payout_events = [e for e in const.HANDLED_WEBHOOK_EVENTS if e.startswith('PAYOUT')]

        self.assertFalse(
            payout_events,
            msg=(
                "A payout groups many payments into one settlement and matches no single "
                "transaction. Subscribing to payout events only produces notifications that are "
                f"logged as unmatched. Found: {payout_events}."
            ),
        )

    def test_default_payment_method_codes(self):
        self.assertEqual(
            self.provider._get_default_payment_method_codes(), const.DEFAULT_PAYMENT_METHODS_CODES,
            msg=(
                "These are the payment methods activated when Revolut is activated. A mismatch "
                "means a merchant enables Revolut and finds no usable payment method on the "
                "checkout page."
            ),
        )

    def test_default_payment_method_codes_of_another_provider_are_untouched(self):
        self.assertNotEqual(
            self.dummy_provider._get_default_payment_method_codes(),
            const.DEFAULT_PAYMENT_METHODS_CODES,
            msg=(
                "The override must return early for another provider, otherwise activating any "
                "provider would activate Revolut's payment methods."
            ),
        )

    def test_secret_key_is_required_to_enable_the_provider(self):
        """ An enabled provider without a key would fail on the customer's first payment. """
        with self.assertRaises(
            ValidationError,
            msg=(
                "`required_if_provider='revolut'` must keep an enabled provider from losing its "
                "API key. Without it, the failure surfaces on a customer's payment instead of on "
                "the form of whoever emptied the field."
            ),
        ):
            self.provider.write({'revolut_secret_key': False})

    def test_secret_fields_are_hidden_from_non_system_users(self):
        """ The API key and the signing secret are the credentials of the merchant account. """
        provider = self.env['payment.provider'].with_user(self.internal_user)
        for field_name in ('revolut_secret_key', 'revolut_webhook_secret'):
            with self.subTest(field_name=field_name):
                with self.assertRaises(
                    AccessError,
                    msg=(
                        f"{field_name} must stay restricted to `base.group_system`. It is a "
                        f"credential of the merchant account: anyone who can read it can charge "
                        f"and refund in the merchant's name."
                    ),
                ):
                    provider.check_field_access_rights('read', [field_name])

    # === Webhook management === #

    # === Credentials page: what it can warn about before the click === #

    def test_webhook_url_mirrors_what_the_action_registers(self):
        """ The form must show the very URL the button would send to Revolut. """
        self.assertEqual(
            self.provider.revolut_webhook_url, self.provider._revolut_get_webhook_url(),
            msg=(
                "The Credentials page shows this URL so the address can be checked before "
                "registering it. Computing it differently from the action would advertise one "
                "URL and register another."
            ),
        )

    def test_webhook_url_is_flagged_https(self):
        self.assertTrue(self.provider.revolut_webhook_url_is_https)

    def test_webhook_url_is_flagged_when_not_https(self):
        """ A database on http cannot register a webhook — the form says so instead of
        offering a button that raises. """
        self.env['ir.config_parameter'].sudo().set_param('web.base.url', 'http://localhost:8069')
        self.provider.invalidate_recordset(
            ['revolut_webhook_url', 'revolut_webhook_url_is_https']
        )
        self.assertFalse(
            self.provider.revolut_webhook_url_is_https,
            msg=(
                "`action_revolut_create_webhook` refuses a non-HTTPS URL. The flag is what "
                "hides the button, so a wrong value here brings back the click-then-read-the-"
                "error flow this replaced."
            ),
        )
        self.assertIn('localhost', self.provider.revolut_webhook_url)

    def test_webhook_url_is_empty_on_another_provider(self):
        other = self._prepare_provider('none')
        self.assertFalse(other.revolut_webhook_url)
        self.assertFalse(other.revolut_webhook_url_is_https)

    def test_webhook_url_compute_makes_no_request(self):
        """ The Credentials page renders on every form open; it must never call Revolut.

        A network call in a compute would turn a form open into an API round trip — slow,
        and failing whenever Revolut is unreachable.
        """
        with patch(REQUEST_PATH, side_effect=AssertionError("the compute called the API")):
            self.provider.invalidate_recordset(
                ['revolut_webhook_url', 'revolut_webhook_url_is_https']
            )
            self.assertTrue(self.provider.revolut_webhook_url)
            self.assertTrue(self.provider.revolut_webhook_url_is_https)

    def test_webhook_creation_requires_the_secret_key(self):
        """ The call that creates the webhook is itself authenticated with the API key. """
        self.provider.write({'state': 'disabled', 'revolut_secret_key': False})

        with self.assertRaises(ValidationError) as error:
            self.provider.action_revolut_create_webhook()

        self.assertIn(
            "secret API key", str(error.exception),
            msg=(
                "Pressing the webhook button without an API key must say exactly that. The call "
                "would otherwise fail as a bare 401 from Revolut, which says nothing about what "
                "the merchant has to fill in.\n"
                f"    message raised: {error.exception}"
            ),
        )

    def test_webhook_creation_requires_an_https_url(self):
        """ Revolut refuses a plain HTTP webhook, and says so with an unhelpful error. """
        self.env['ir.config_parameter'].sudo().set_param('web.base.url', 'http://odoo.example.com')

        with self.assertRaises(ValidationError) as error:
            self.provider.action_revolut_create_webhook()

        self.assertIn(
            "HTTPS", str(error.exception),
            msg=(
                "The error must name the real problem — `web.base.url` is not public HTTPS — "
                "instead of letting Revolut answer with a generic bad request.\n"
                f"    message raised: {error.exception}"
            ),
        )

    def test_webhook_is_created_with_the_handled_events(self):
        """ Revolut rejects unknown event names, so the list must be the one the module handles. """
        with patch(REQUEST_PATH, side_effect=[[], self.created_webhook_data]) as api:
            self.provider.action_revolut_create_webhook()

        self.assertApiCalls(api, [
            call('1.0/webhooks', method='GET'),
            call('1.0/webhooks', payload={
                'url': self.webhook_url, 'events': const.HANDLED_WEBHOOK_EVENTS
            }),
        ], why=(
            "Setting up the webhook must first list the existing ones, then create one for this "
            "database's URL subscribed to exactly the events this module handles. A missing event "
            "means Odoo is never told about that half of the payment flow."
        ))
        self.assertEqual(
            self.provider.revolut_webhook_secret, 'wsk_created',
            msg=(
                "The signing secret returned at creation must be stored: Revolut never discloses "
                "it again, and without it every notification is refused."
            ),
        )

    def test_existing_webhook_is_updated_and_its_secret_rotated(self):
        """ Revolut allows one webhook per URL, and never discloses an existing secret again.

        Rotating is also what makes the button safe to press on a database copy: the copy gets a
        secret of its own instead of silently sharing the one of the original database.
        """
        with patch(
            REQUEST_PATH, side_effect=[self.webhooks_list_data, {}, self.rotated_webhook_data]
        ) as api:
            self.provider.action_revolut_create_webhook()

        self.assertApiCalls(api, [
            call('1.0/webhooks', method='GET'),
            call(
                f'1.0/webhooks/{self.webhook_id}',
                payload={'url': self.webhook_url, 'events': const.HANDLED_WEBHOOK_EVENTS},
                method='PUT',
            ),
            call(f'1.0/webhooks/{self.webhook_id}/rotate-signing-secret', payload={}),
        ], why=(
            "A webhook already registered for this URL must be updated in place and its secret "
            "rotated. Creating a second one is refused by Revolut, and skipping the rotation "
            "leaves this database with no usable secret."
        ))
        self.assertEqual(
            self.provider.revolut_webhook_secret, 'wsk_rotated',
            msg="The rotated secret must replace the stored one, or notifications keep being refused.",
        )

    def test_webhook_of_another_database_is_left_alone(self):
        """ The merchant account is shared; webhooks of other databases must not be touched. """
        other_database_webhook = [self.webhooks_list_data[0]]

        with patch(REQUEST_PATH, side_effect=[other_database_webhook, self.created_webhook_data]):
            self.provider.action_revolut_create_webhook()

        self.assertEqual(
            self.provider.revolut_webhook_secret, 'wsk_created',
            msg=(
                "Only a webhook whose URL is this database's may be reused. Rotating the secret of "
                "another database's webhook would silently stop that database from receiving any "
                "notification."
            ),
        )

    def test_webhook_action_returns_a_notification(self):
        with patch(REQUEST_PATH, side_effect=[[], self.created_webhook_data]):
            action = self.provider.action_revolut_create_webhook()

        self.assertEqual(
            action.get('tag'), 'display_notification',
            msg=(
                "The button must give visible feedback: silence is indistinguishable from a button "
                f"that does nothing.\n    action returned: {action}"
            ),
        )

    def test_webhook_action_is_a_no_op_on_another_provider(self):
        with patch(REQUEST_PATH) as api:
            result = self.dummy_provider.action_revolut_create_webhook()

        self.assertIsNone(
            result, msg="The action must return early for a provider that is not Revolut."
        )
        self.assertNoApiCall(api, why=(
            "The action must send nothing when called on another provider, whose credentials are "
            "not Revolut's and whose URL has nothing to do with a Revolut webhook."
        ))
