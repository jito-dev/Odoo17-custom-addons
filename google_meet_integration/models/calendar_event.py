from odoo import api, fields, models


class CalendarEvent(models.Model):
    _inherit = 'calendar.event'

    # 'google_meet_rest' is the DISPLAY/redirection label for a calendar event
    # whose videocall_location is a meet.google.com URL — NOT a REST-minting
    # trigger (the up-front REST mint was removed). The Meet URL itself is put
    # there by the NATIVE Google Calendar sync. This value + the computes below
    # are a contract relied on by hr_recruitment_call_stage_google_meet (its
    # tests assert event.videocall_source == 'google_meet_rest'); keep them.
    videocall_source = fields.Selection(
        selection_add=[('google_meet_rest', 'Google Meet')],
    )

    @api.depends('videocall_location')
    def _compute_videocall_source(self):
        super()._compute_videocall_source()
        for event in self:
            if event.videocall_location and 'meet.google.com' in event.videocall_location:
                event.videocall_source = 'google_meet_rest'

    @api.depends('videocall_source', 'videocall_location')
    def _compute_videocall_redirection(self):
        super()._compute_videocall_redirection()
        for event in self:
            if event.videocall_source == 'google_meet_rest' and event.videocall_location:
                event.videocall_redirection = event.videocall_location
