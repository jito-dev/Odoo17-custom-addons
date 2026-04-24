from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    quick_report_team_id = fields.Many2one(
        'helpdesk.team',
        string="Quick Report Helpdesk Team",
        config_parameter='jito_helpdesk_quick_report.default_team_id',
        help="Default helpdesk team for tickets created via the Quick Report context menu. "
             "If not set, the system will auto-detect a suitable team.",
    )
    quick_report_screenshot_strategy = fields.Selection(
        [
            ('auto', 'Auto (Screen Capture API, fallback to DOM capture)'),
            ('screen_capture', 'Screen Capture API only'),
            ('dom_capture', 'DOM capture (html2canvas) only'),
            ('none', 'Disabled'),
        ],
        string="Screenshot Strategy",
        config_parameter='jito_helpdesk_quick_report.screenshot_strategy',
        default='dom_capture',
        help="Choose how screenshots are captured when reporting issues.\n"
             "- Auto: tries native Screen Capture API first, falls back to DOM capture.\n"
             "- Screen Capture API: uses browser screen sharing (requires user permission).\n"
             "- DOM capture: renders the page DOM to an image (no permission needed).\n"
             "- Disabled: no screenshot is captured.",
    )
