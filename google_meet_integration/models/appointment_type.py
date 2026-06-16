# -*- coding: utf-8 -*-
from odoo import fields, models


class AppointmentType(models.Model):
    _inherit = 'appointment.type'

    # Make Google Meet the default (and, with the hidden selector in
    # views/appointment_type_views.xml, effectively the only) videoconference
    # source for every Appointment Type — for an organisation that does not use
    # Odoo Discuss video. We redefine ONLY the default of the native Selection;
    # the values themselves (incl. the 'google_meet' option added by
    # appointment_google_calendar) are inherited untouched. 'google_meet' is a
    # valid value here because this module depends on appointment_google_calendar.
    event_videocall_source = fields.Selection(default='google_meet')
