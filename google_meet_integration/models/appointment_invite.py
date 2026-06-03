from odoo import fields, models


class AppointmentInvite(models.Model):
    _inherit = 'appointment.invite'

    meet_space_url = fields.Char(
        string='Google Meet Space',
        copy=False,
        help='Cached Google Meet URL minted for this invite. One invite '
             'maps to one (recipient, appointment type), so reusing the same '
             'space keeps a stable join link across reschedules and avoids '
             'minting a fresh Meet space on every booking (Meet API quota is '
             '60 QPM per GCP project). Empty until the first booking mints it.',
    )
