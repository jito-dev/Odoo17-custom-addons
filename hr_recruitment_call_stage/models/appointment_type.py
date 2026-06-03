# -*- coding: utf-8 -*-
from odoo import _, api, models
from odoo.exceptions import UserError


class AppointmentType(models.Model):
    _inherit = 'appointment.type'

    # Etap 2 (v17.0.2.0.0) — replaces the previous ondelete='restrict'
    # safety we had on the dropped link model. Block deletion of an
    # appointment type while any applicant-linked invite still uses it,
    # so a candidate's saved booking URL cannot 404 mid-flow.
    @api.ondelete(at_uninstall=False)
    def _unlink_except_recruitment_live_invites(self):
        Invite = self.env['appointment.invite'].sudo()
        blocking = Invite.search([
            ('appointment_type_ids', 'in', self.ids),
            ('applicant_id', '!=', False),
        ], limit=1)
        if blocking:
            raise UserError(_(
                "Cannot delete appointment type '%(name)s' because it is "
                "still linked to at least one recruitment booking invite "
                "(applicant: %(applicant)s). Reassign or archive the "
                "applicant's booking first.",
                name=blocking.appointment_type_ids[:1].display_name,
                applicant=blocking.applicant_id.display_name,
            ))
