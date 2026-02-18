# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError
from .coder_api import CoderAPI
import logging

_logger = logging.getLogger(__name__)


class ProjectTask(models.Model):
    """
    Extends project.task with Coder.com workspace integration.
    """
    _inherit = 'project.task'

    coder_integration_enabled = fields.Boolean(
        string="Coder Integration Enabled",
        default=False,
        help="Enable Coder workspace integration for this task."
    )

    coder_workspace_id = fields.Selection(
        selection='_get_workspace_selection',
        string="Coder Workspace",
        help="Choose a workspace from your Coder account."
    )

    coder_workspace_status = fields.Char(
        string="Workspace Status",
        readonly=True,
        help="Current status of the Coder workspace."
    )

    # Status emoji mapping
    STATUS_EMOJI_MAP = {
        'pending': '⏳ Pending',
        'starting': '🚀 Starting',
        'running': '✅ Running',
        'stopping': '⏸️ Stopping',
        'stopped': '⏹️ Stopped',
        'failed': '❌ Failed',
        'canceling': '🚫 Canceling',
        'canceled': '🚫 Canceled',
        'deleting': '🗑️ Deleting',
        'deleted': '🗑️ Deleted',
        'unknown': '❓ Unknown',
        'error': '⚠️ Error',
        'timeout': '⏱️ Timeout',
    }

    def _get_coder_api(self, raise_on_error=True):
        """
        Get configured Coder API instance.

        Args:
            raise_on_error (bool): Raise UserError if not configured

        Returns:
            CoderAPI: Configured API instance

        Raises:
            UserError: If Coder is not configured and raise_on_error=True
        """
        company = self.company_id or self.env.company

        if not company.coder_enabled or not company.coder_api_token:
            if raise_on_error:
                raise UserError("Coder is not configured. Please check Settings.")
            return None

        return CoderAPI(company.coder_base_url, company.coder_api_token)

    def _format_workspace_status(self, status):
        """Format workspace status with emoji."""
        return self.STATUS_EMOJI_MAP.get(
            status.lower(),
            f'❓ {status.capitalize()}'
        )

    def _fetch_workspace_status(self):
        """
        Fetch workspace status via SSE and update field.

        Returns:
            bool: True if successful
        """
        if not self.coder_workspace_id:
            self.coder_workspace_status = False
            return False

        try:
            api = self._get_coder_api(raise_on_error=False)
            if not api:
                self.coder_workspace_status = self._format_workspace_status('unknown')
                return False

            status = api.get_workspace_status_sse(self.coder_workspace_id)
            self.coder_workspace_status = self._format_workspace_status(status)
            return True

        except Exception as e:
            _logger.warning(f"Failed to fetch workspace status: {str(e)}")
            self.coder_workspace_status = self._format_workspace_status('error')
            return False

    @api.onchange('coder_workspace_id')
    def _onchange_coder_workspace_id(self):
        """Auto-fetch workspace status when workspace is selected."""
        self._fetch_workspace_status()

    @api.model
    def _get_workspace_selection(self):
        """
        Dynamically populate workspace selection from Coder API.

        Returns:
            list: List of (id, name) tuples
        """
        try:
            api = self._get_coder_api(raise_on_error=False)
            if not api:
                return [('', 'Coder not configured')]

            workspaces = api.get_workspaces()
            selection = [(ws['id'], ws['name']) for ws in workspaces]

            return selection if selection else [('', 'No workspaces found')]

        except Exception as e:
            _logger.warning(f"Failed to fetch workspaces: {str(e)}")
            return [('', 'Error loading workspaces')]

    def action_enable_coder_integration(self):
        """Enable Coder integration for this task."""
        self.ensure_one()

        # Verify configuration
        api = self._get_coder_api(raise_on_error=True)
        if not api:
            raise UserError("Coder integration is not enabled in Settings.")

        self.coder_integration_enabled = True

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Coder Integration Enabled',
                'message': 'You can now select a workspace for this task.',
                'type': 'success',
                'sticky': False,
            }
        }

    def action_disable_coder_integration(self):
        """Disable Coder integration for this task."""
        self.ensure_one()
        self.coder_integration_enabled = False

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Coder Integration Disabled',
                'message': 'Coder workspace field has been hidden.',
                'type': 'info',
                'sticky': False,
            }
        }

    def action_refresh_workspace_status(self):
        """Manually refresh workspace status."""
        self.ensure_one()

        if not self.coder_workspace_id:
            raise UserError("No workspace selected.")

        # Verify configuration
        self._get_coder_api(raise_on_error=True)

        # Fetch status
        if not self._fetch_workspace_status():
            raise UserError("Failed to refresh status. Check logs for details.")

        return True

    def action_open_coder_workspace(self):
        """Open Coder workspace in new browser tab."""
        self.ensure_one()

        if not self.coder_workspace_id:
            raise UserError("No workspace selected.")

        try:
            api = self._get_coder_api(raise_on_error=True)
            workspaces = api.get_workspaces()

            # Find selected workspace
            workspace_info = next(
                (ws for ws in workspaces if ws['id'] == self.coder_workspace_id),
                None
            )

            if not workspace_info:
                raise UserError("Workspace not found.")

            # Construct URL
            company = self.company_id or self.env.company
            workspace_url = (
                f"{company.coder_base_url}/@"
                f"{workspace_info['owner_name']}/"
                f"{workspace_info['name']}"
            )

            return {
                'type': 'ir.actions.act_url',
                'url': workspace_url,
                'target': 'new',
            }

        except UserError:
            raise
        except Exception as e:
            raise UserError(f"Failed to open workspace: {str(e)}")
