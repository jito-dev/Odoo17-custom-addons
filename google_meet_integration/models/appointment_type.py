import logging

from markupsafe import Markup

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class AppointmentType(models.Model):
    _inherit = 'appointment.type'

    event_videocall_source = fields.Selection(
        selection_add=[('google_meet', 'Google Meet')],
        ondelete={'google_meet': 'set default'},
    )
    users_wo_google_meet_msg = fields.Html(
        string="Google Meet Connection Warning",
        compute='_compute_users_wo_google_meet_msg',
    )

    @api.depends('staff_user_ids', 'event_videocall_source')
    def _compute_users_wo_google_meet_msg(self):
        self.users_wo_google_meet_msg = False
        fallback = self.env['google.meet.service']._get_fallback_user()
        for appointment_type in self.filtered(
            lambda at: at.event_videocall_source == 'google_meet'
        ):
            unsynced = appointment_type.staff_user_ids.filtered(
                lambda user: not self._user_has_google_token(user)
            )
            if unsynced and not fallback:
                names = Markup(', ').join(
                    Markup('<b>%s</b>') % user.name for user in unsynced
                )
                appointment_type.users_wo_google_meet_msg = _(
                    "%(names)s have not connected their Google Calendar. "
                    "Bookings assigned to them will be created without a Meet link "
                    "unless an administrator configures a fallback Meet user in Settings.",
                    names=names,
                )

    @staticmethod
    def _user_has_google_token(user):
        try:
            return bool(user.sudo()._get_google_calendar_token())
        except Exception:
            return False

    def _prepare_calendar_event_values(
        self, asked_capacity, booking_line_values, description, duration,
        appointment_invite, guests, name, customer, staff_user, start, stop,
    ):
        values = super()._prepare_calendar_event_values(
            asked_capacity, booking_line_values, description, duration,
            appointment_invite, guests, name, customer, staff_user, start, stop,
        )
        if self.event_videocall_source == 'google_meet' and not values.get('videocall_location'):
            preferred_user = staff_user or self.create_uid
            try:
                values['videocall_location'] = self.env['google.meet.service']._mint_meet_space(
                    preferred_user,
                )
            except Exception:
                _logger.exception(
                    "Google Meet mint failed for appointment type %s; "
                    "booking will proceed without a videocall link.",
                    self.id,
                )
        return values
