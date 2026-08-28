import logging
import pprint

import requests
from werkzeug.urls import url_join, url_parse

from odoo import _, api, fields, models, service
from odoo.exceptions import ValidationError

from odoo.addons.payment_revolut import const
from odoo.addons.payment_revolut.controllers.main import RevolutController

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('revolut', "Revolut")], ondelete={'revolut': 'set default'}
    )
    revolut_secret_key = fields.Char(
        string="Revolut Secret API Key",
        help="The Merchant API secret key (sk_...) of the environment selected in the State "
             "field: the sandbox key while in test mode, the production key once enabled.",
        required_if_provider='revolut',
        groups='base.group_system',
    )
    revolut_webhook_secret = fields.Char(
        string="Revolut Webhook Signing Secret",
        help="The signing secret (wsk_...) of the webhook that notifies Odoo of the payment "
             "result. Filled in by the 'Generate your webhook' button.",
        groups='base.group_system',
    )
    revolut_alert_user_id = fields.Many2one(
        string="Payment Alerts Responsible",
        comodel_name='res.users',
        domain="[('share', '=', False)]",
        help="The accountant who is told when a Revolut payment needs a human: an amount that "
             "does not match the transaction, or a payment that stays pending for too long. "
             "Left empty, the alerts go to the first accountant of the company, which is rarely "
             "the person you want.",
    )

    # The two fields below exist only so the Credentials page can warn BEFORE
    # the click fails: `action_revolut_create_webhook` refuses a non-HTTPS URL,
    # and a form that offers the button anyway teaches the user to click and
    # read an error. Stock providers keep display logic in the
    # view (no `compute=` anywhere in payment_*/models/payment_provider.py) —
    # these two are the exception because a view expression can neither join a
    # base URL to a route nor inspect a URL scheme.
    revolut_webhook_url = fields.Char(
        string="Webhook URL",
        compute='_compute_revolut_webhook_url',
        help="The address Revolut is told to notify. It follows the 'web.base.url' system "
             "parameter, so it changes with the public address of this database.",
    )
    revolut_webhook_url_is_https = fields.Boolean(
        compute='_compute_revolut_webhook_url',
    )

    # === COMPUTE METHODS === #

    @api.depends('code')
    def _compute_revolut_webhook_url(self):
        """ Mirror the URL `action_revolut_create_webhook` would register.

        Not stored, and deliberately free of any network call: it reads the
        `web.base.url` system parameter through `get_base_url()`, so it stays
        truthful when that parameter changes without the provider being
        touched.
        """
        for provider in self:
            if provider.code != 'revolut':
                provider.revolut_webhook_url = False
                provider.revolut_webhook_url_is_https = False
                continue
            url = provider._revolut_get_webhook_url()
            provider.revolut_webhook_url = url
            provider.revolut_webhook_url_is_https = url_parse(url).scheme == 'https'

    def _compute_feature_support_fields(self):
        """ Override of `payment` to enable additional features. """
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == 'revolut').update({
            # Revolut refunds any amount up to the captured total, in as many steps as needed.
            'support_refund': 'partial',
            # Captures are supported, but only for the full authorised amount: a partial capture
            # would leave Odoo tracking child transactions that Revolut does not model the same
            # way, so it is deliberately not offered.
            'support_manual_capture': 'full_only',
        })

    # === BUSINESS METHODS === #

    def _get_supported_currencies(self):
        """ Override of `payment` to return the supported currencies. """
        supported_currencies = super()._get_supported_currencies()
        if self.code == 'revolut':
            supported_currencies = supported_currencies.filtered(
                lambda c: c.name in const.SUPPORTED_CURRENCIES
            )
        return supported_currencies

    def _get_default_payment_method_codes(self):
        """ Override of `payment` to return the default payment method codes. """
        default_codes = super()._get_default_payment_method_codes()
        if self.code != 'revolut':
            return default_codes
        return const.DEFAULT_PAYMENT_METHODS_CODES

    def _revolut_get_api_url(self):
        """ Return the API host matching the environment of this provider.

        Sandbox and production are separate Revolut installations with separate keys, and the
        provider state is what tells them apart: a provider in `test` state is expected to hold a
        sandbox key. There is no way to tell the two apart from the key itself.

        Note: `self.ensure_one()`

        :return: The base URL of the Merchant API.
        :rtype: str
        """
        self.ensure_one()
        return const.API_URLS['sandbox' if self.state == 'test' else 'production']

    def _revolut_make_request(self, endpoint, payload=None, method='POST'):
        """ Make a request to the Revolut Merchant API and return the JSON-formatted content.

        Note: `self.ensure_one()`

        :param str endpoint: The endpoint to be reached by the request.
        :param dict payload: The payload of the request.
        :param str method: The HTTP method of the request.
        :return: The JSON-formatted content of the response.
        :rtype: dict
        :raise ValidationError: If an HTTP error occurs.
        """
        self.ensure_one()

        url = url_join(f'{self._revolut_get_api_url()}/api/', endpoint.strip('/'))
        odoo_version = service.common.exp_version()['server_version']
        module_version = self.env.ref('base.module_payment_revolut').installed_version
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.revolut_secret_key}',
            'Content-Type': 'application/json',
            # Required on every request; the payload shape depends on it.
            'Revolut-Api-Version': const.API_VERSION,
            'User-Agent': f'Odoo/{odoo_version} RevolutOdoo/{module_version}',
        }
        try:
            response = requests.request(method, url, json=payload, headers=headers, timeout=60)
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError:
                _logger.exception(
                    "Revolut refused the %s request at %s with HTTP %s.\nSent:\n%s\nReceived:\n%s",
                    method, url, response.status_code, pprint.pformat(payload),
                    self._revolut_extract_error_message(response)
                )
                raise ValidationError("Revolut: " + _(
                    "The communication with the API failed. Revolut gave us the following "
                    "information: '%s'", self._revolut_extract_error_message(response)
                ))
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as error:
            _logger.exception(
                "Unable to reach Revolut with a %s request at %s (%s). Check the outgoing network "
                "access of this database.", method, url, type(error).__name__
            )
            raise ValidationError("Revolut: " + _(
                "Could not establish the connection to the API at %s.", url
            ))
        # A successful DELETE answers 204 with an empty body, which is not valid JSON.
        return response.json() if response.content else {}

    @staticmethod
    def _revolut_extract_error_message(response):
        """ Return the most informative error message the response holds.

        Revolut answers validation errors with a `message`, but answers some errors with an
        `errorId` alone; returning the raw body then is more useful than returning nothing.

        :param requests.Response response: The error response.
        :return: The error message.
        :rtype: str
        """
        try:
            error_data = response.json()
        except ValueError:
            return response.text[:300]
        return error_data.get('message') or response.text[:300]

    # === BUSINESS METHODS - ALERTS === #

    def _revolut_get_alert_user(self):
        """ Return the user who has to look at a payment that needs a human.

        The responsible is configured on the provider. It falls back to an accountant of the same
        company so that an alert is never silently dropped on a database where nobody filled the
        field in — but the fallback is announced, because an alert landing on an arbitrary
        accountant is a configuration to fix, not a working setup.

        Note: `self.ensure_one()`

        :return: The user to notify, empty if this database has no accountant at all.
        :rtype: recordset of `res.users`
        """
        self.ensure_one()

        if self.revolut_alert_user_id:
            return self.revolut_alert_user_id

        group = self.env.ref('account.group_account_manager', raise_if_not_found=False)
        if not group:  # Accounting is not installed: there is no accountant to alert.
            _logger.warning(
                "No responsible is set on the Revolut provider %s and this database has no "
                "accounting groups, so payment alerts have nobody to go to. Set the 'Payment "
                "Alerts Responsible' field on the provider.", self.display_name
            )
            return self.env['res.users']

        candidates = group.users.filtered(
            lambda u: u.active and (not self.company_id or self.company_id in u.company_ids)
        )
        # `base.user_root` runs the crons and reads no inbox, so alerting it means alerting nobody.
        root = self.env.ref('base.user_root', raise_if_not_found=False)
        if root:
            candidates -= root
        user = candidates[:1]
        if user:
            _logger.warning(
                "No responsible is set on the Revolut provider %s; falling back to the accountant "
                "%s for payment alerts. Set the 'Payment Alerts Responsible' field on the provider "
                "so that they reach the right person.", self.display_name, user.display_name
            )
        else:
            _logger.warning(
                "No responsible is set on the Revolut provider %s and no accountant was found to "
                "fall back on, so payment alerts have nobody to go to. Set the 'Payment Alerts "
                "Responsible' field on the provider.", self.display_name
            )
        return user

    # === WEBHOOK MANAGEMENT === #

    def _revolut_get_webhook_url(self):
        """ Return the public URL Revolut must notify.

        Note: `self.ensure_one()`

        :return: The webhook URL.
        :rtype: str
        """
        self.ensure_one()
        return url_join(self.get_base_url(), RevolutController._webhook_url)

    def action_revolut_create_webhook(self):
        """ Create or re-synchronise the webhook on Revolut and store its signing secret.

        Revolut allows a single webhook per URL, so an existing webhook on this database's URL is
        updated in place and its secret rotated rather than duplicated. Rotating is also what makes
        the button safe to press again after a database copy: the copy gets a fresh secret instead
        of silently sharing one.

        :return: A feedback notification.
        :rtype: dict
        """
        self.ensure_one()

        if self.code != 'revolut':
            return
        if not self.revolut_secret_key:
            raise ValidationError(
                "Revolut: " + _("Fill in the secret API key before generating the webhook.")
            )

        webhook_url = self._revolut_get_webhook_url()
        if url_parse(webhook_url).scheme != 'https':
            raise ValidationError("Revolut: " + _(
                "Revolut only accepts a public HTTPS webhook URL, but this database resolves to "
                "%s. Set the 'web.base.url' system parameter to the public address of this "
                "database first.", webhook_url
            ))

        _logger.info(
            "Synchronising the Revolut webhook of the provider %s (%s) at %s.",
            self.display_name, self.state, webhook_url
        )
        existing_webhooks = self._revolut_make_request('1.0/webhooks', method='GET')
        webhook = next(
            (w for w in existing_webhooks if w.get('url') == webhook_url), None
        )
        if webhook:  # Align its events, then rotate its secret to get one we can store.
            _logger.info(
                "Reusing the existing Revolut webhook %s: aligning its events and rotating its "
                "signing secret.", webhook['id']
            )
            self._revolut_make_request(
                f'1.0/webhooks/{webhook["id"]}',
                payload={'url': webhook_url, 'events': const.HANDLED_WEBHOOK_EVENTS},
                method='PUT',
            )
            webhook = self._revolut_make_request(
                f'1.0/webhooks/{webhook["id"]}/rotate-signing-secret', payload={}
            )
            message = _("The existing Revolut webhook was updated and its signing secret renewed.")
        else:
            _logger.info(
                "No Revolut webhook exists yet for %s; creating one for the events %s.",
                webhook_url, ', '.join(const.HANDLED_WEBHOOK_EVENTS)
            )
            webhook = self._revolut_make_request(
                '1.0/webhooks',
                payload={'url': webhook_url, 'events': const.HANDLED_WEBHOOK_EVENTS},
            )
            message = _("Your Revolut webhook was successfully set up.")

        # The secret itself is never logged: it is what proves a notification comes from Revolut.
        if not webhook.get('signing_secret'):
            _logger.warning(
                "Revolut returned the webhook %s without a signing secret; notifications will be "
                "refused until a secret is stored.", webhook.get('id')
            )
        else:
            _logger.info("Stored the signing secret of the Revolut webhook %s.", webhook.get('id'))
        self.revolut_webhook_secret = webhook.get('signing_secret')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': message,
                'type': 'info',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
