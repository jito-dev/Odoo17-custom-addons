import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class QuickReportController(http.Controller):

    @http.route(
        '/jito_helpdesk_quick_report/create_ticket',
        type='json',
        auth='user',
        methods=['POST'],
    )
    def create_ticket(self, name, description, screenshot_base64=False, priority='1'):
        """Create a helpdesk ticket with auto-captured context.

        Called from the JS quick report service. Uses sudo() because
        regular internal users (base.group_user) may not have create
        access on helpdesk.ticket.
        """
        team_id = self._get_team_id()
        if not team_id:
            return {'error': 'No helpdesk team found. Please configure one in Settings.'}

        ticket = request.env['helpdesk.ticket'].sudo().create({
            'name': name,
            'description': description,
            'team_id': team_id,
            'partner_id': request.env.user.partner_id.id,
            'priority': priority or '1',
        })

        if screenshot_base64:
            request.env['ir.attachment'].sudo().create({
                'name': 'screenshot.png',
                'datas': screenshot_base64,
                'res_model': 'helpdesk.ticket',
                'res_id': ticket.id,
                'type': 'binary',
            })

        _logger.info(
            'Quick report ticket %s created by user %s',
            ticket.ticket_ref, request.env.user.login,
        )

        return {
            'ticket_id': ticket.id,
            'ticket_ref': ticket.ticket_ref,
        }

    @http.route(
        '/jito_helpdesk_quick_report/get_settings',
        type='json',
        auth='user',
        methods=['POST'],
    )
    def get_settings(self):
        """Return current quick report settings for the JS service."""
        ICP = request.env['ir.config_parameter'].sudo()
        return {
            'screenshot_strategy': ICP.get_param(
                'jito_helpdesk_quick_report.screenshot_strategy', default='dom_capture',
            ),
        }

    def _get_team_id(self):
        """Resolve the helpdesk team to use.

        Priority:
        1. Configured default team from ir.config_parameter
        2. First team where current user is a member
        3. First available team
        """
        ICP = request.env['ir.config_parameter'].sudo()
        configured_id = ICP.get_param(
            'jito_helpdesk_quick_report.default_team_id', default=False,
        )
        if configured_id:
            try:
                team_id = int(configured_id)
                if request.env['helpdesk.team'].sudo().browse(team_id).exists():
                    return team_id
            except (ValueError, TypeError):
                pass

        # Fallback: team where current user is a member
        team = request.env['helpdesk.team'].sudo().search(
            [('member_ids', 'in', [request.env.uid])], limit=1,
        )
        if team:
            return team.id

        # Last resort: any team
        team = request.env['helpdesk.team'].sudo().search([], limit=1)
        return team.id if team else False
