# -*- coding: utf-8 -*-
"""Transient record backing the OWL email-preview dialog (v17.0.23.0.0).

``hr.job.stage.config.action_preview_email`` renders the effective
call-invite template against a sample applicant and stashes the result here,
then opens this record's form in a ``target='new'`` dialog. The form embeds a
small OWL field widget (``call_stage_email_preview``) that renders
``rendered_body`` inside an ``<iframe srcdoc>`` — fully styled, isolated from
the backend CSS — with a desktop/mobile width toggle and the resolved
Book-a-call button highlighted. ``has_button`` drives the red "no button"
banner.

The footer carries a **"Back to settings"** action (``action_back_to_config``,
v17.0.24.8.0): it re-opens the originating Call Stage config form. Because the
return goes through the action service, opening that form cleanly removes the
preview dialog instead of relying on Odoo's fragile dialog-on-dialog
stacking — the recruiter always lands back on a working config form, and a
plain "Close" never silently takes the whole stack down with it.
"""
from odoo import _, fields, models


class HrCallStagePreview(models.TransientModel):
    _name = 'hr.call.stage.preview'
    _description = 'Call Stage email preview'

    config_id = fields.Many2one(
        'hr.job.stage.config', string='Call Stage config', ondelete='cascade')
    subject = fields.Char(string='Subject', readonly=True)
    rendered_body = fields.Html(
        string='Rendered email', readonly=True, sanitize=False,
        help='Fully QWeb-rendered email body, shown in an isolated iframe.')
    booking_url = fields.Char(string='Resolved booking URL', readonly=True)
    has_button = fields.Boolean(string='Booking button present', readonly=True)
    device = fields.Selection(
        [('desktop', 'Desktop'), ('mobile', 'Mobile')],
        string='Preview width', default='desktop', required=True)

    def action_back_to_config(self):
        """Re-open the originating Call Stage config form.

        Returning an ``act_window`` (``target='new'``) routes through the web
        action service, which removes the current preview dialog as it opens
        the config form — so the recruiter reliably returns to a fully usable
        Call Stage settings form regardless of how Odoo stacked the dialogs.
        Falls back to simply closing the preview when the config was somehow
        lost (transient cleanup / direct test calls).
        """
        self.ensure_one()
        if not self.config_id:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': _('Call Stage settings'),
            'res_model': 'hr.job.stage.config',
            'res_id': self.config_id.id,
            'view_mode': 'form',
            'target': 'new',
        }
