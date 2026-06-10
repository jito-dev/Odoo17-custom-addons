from . import models

# from odoo.exceptions import UserError


# def _post_init_check_conflicts(env):
#     conflict = env['ir.module.module'].search([
#         ('name', '=', 'appointment_google_calendar'),
#         ('state', 'in', ('installed', 'to install', 'to upgrade')),
#     ])
#     if conflict:
#         raise UserError(
#             "google_meet_integration is incompatible with appointment_google_calendar "
#             "because both claim the 'google_meet' videoconference source with different "
#             "implementations. Uninstall appointment_google_calendar before installing "
#             "this module."
#         )
