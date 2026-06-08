import json
import logging

import requests

from odoo import _, api, models
from odoo.exceptions import RedirectWarning, UserError

_logger = logging.getLogger(__name__)

MEET_API_URL = 'https://meet.googleapis.com/v2/spaces'
REQUEST_TIMEOUT = 15


class GoogleMeetService(models.AbstractModel):
    _name = 'google.meet.service'
    _description = 'Google Meet REST API v2 client'

    @api.model
    def _get_fallback_user(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'google_meet_integration.fallback_user_id'
        )
        if not param:
            return self.env['res.users']
        try:
            return self.env['res.users'].sudo().browse(int(param)).exists()
        except (TypeError, ValueError):
            return self.env['res.users']

    @api.model
    def _get_meet_owner(self, preferred_user):
        """Return the first user in the fallback chain with a usable Google token.

        Order: preferred_user -> ir.config_parameter fallback user.
        Returns an empty recordset if neither has a token.
        """
        for user in (preferred_user, self._get_fallback_user()):
            if not user:
                continue
            try:
                if user.sudo()._get_google_calendar_token():
                    return user
            except Exception:
                _logger.warning(
                    "Skipping user %s in Meet fallback chain: token refresh failed",
                    user.login, exc_info=True,
                )
        return self.env['res.users']

    @api.model
    def _mint_meet_space(self, preferred_user):
        """Create a new Meet space and return its ``meetingUri``.

        Raises UserError if no connected user is available, or RedirectWarning
        if the token lacks the Meet scope (so the user can re-consent).
        """
        owner = self._get_meet_owner(preferred_user)
        if not owner:
            raise UserError(_(
                "No Google-connected user is available to create a Google Meet link. "
                "Connect your Google Calendar from Preferences, or ask an administrator "
                "to configure a fallback Meet user in Settings."
            ))

        token = owner.sudo()._get_google_calendar_token()
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }
        try:
            response = requests.post(
                MEET_API_URL,
                headers=headers,
                data=json.dumps({}),
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else 0
            body = error.response.text if error.response is not None else ''
            _logger.warning(
                "Google Meet mint failed (user=%s, status=%s): %s",
                owner.login, status, body,
            )
            if status == 403 and 'insufficient' in body.lower():
                message = _(
                    "Your Google account is authorized for Calendar but not for Meet. "
                    "Disconnect and re-connect Google Calendar from Settings > Calendar "
                    "to grant the additional permission."
                )
                action = self.env.ref(
                    'calendar.calendar_settings_action',
                    raise_if_not_found=False,
                )
                if action:
                    raise RedirectWarning(
                        message, action.id, _("Open Calendar Settings"),
                    )
                raise UserError(message)
            raise UserError(_(
                "Could not create a Google Meet link (HTTP %s). "
                "Check server logs for details.", status,
            ))
        except requests.RequestException as error:
            _logger.warning("Google Meet request error: %s", error)
            raise UserError(_(
                "Could not reach the Google Meet API. Please try again."
            ))

        data = response.json()
        uri = data.get('meetingUri')
        if not uri and data.get('meetingCode'):
            uri = f"https://meet.google.com/{data['meetingCode']}"
        if not uri:
            _logger.error("Google Meet API returned unexpected payload: %s", data)
            raise UserError(_(
                "The Google Meet API did not return a meeting URL."
            ))
        return uri
