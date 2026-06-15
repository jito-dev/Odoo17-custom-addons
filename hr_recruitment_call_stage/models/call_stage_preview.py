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
"""
from odoo import fields, models


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
