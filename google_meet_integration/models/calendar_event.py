from odoo import api, fields, models


class CalendarEvent(models.Model):
    _inherit = 'calendar.event'

    videocall_source = fields.Selection(
        selection_add=[('google_meet', 'Google Meet')],
    )

    @api.depends('videocall_location')
    def _compute_videocall_source(self):
        super()._compute_videocall_source()
        for event in self:
            if event.videocall_location and 'meet.google.com' in event.videocall_location:
                event.videocall_source = 'google_meet'

    def action_set_google_meet_videocall_location(self):
        self.ensure_one()
        uri = self.env['google.meet.service']._mint_meet_space(self.env.user)
        self.videocall_location = uri
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}
