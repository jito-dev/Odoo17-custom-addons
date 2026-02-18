# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request
# Import the standard WebsiteForm controller to extend it
from odoo.addons.website.controllers.form import WebsiteForm
from odoo.addons.website_hr_recruitment.controllers.main import WebsiteHrRecruitment


class WebsiteHrRecruitmentForms(WebsiteHrRecruitment):
    """Extend website recruitment controller to handle custom forms."""

    @http.route(
        '''/jobs/apply/<model("hr.job"):job>''',
        type='http',
        auth="public",
        website=True,
        sitemap=True,
    )
    def jobs_apply(self, job, **kwargs):
        """Override jobs_apply to include form questions if enabled."""
        error = {}
        default = {}
        if 'website_hr_recruitment_error' in request.session:
            error = request.session.pop('website_hr_recruitment_error')
            default = request.session.pop('website_hr_recruitment_default')

        # Get form data if use_forms is enabled
        form_questions = False

        if job.use_forms:
            # Retrieve consolidated questions (Template + Shared + Job Specific)
            # Use sudo() to ensure public user can read linked template/shared questions
            questions = job.sudo().get_form_questions()
            if questions:
                form_questions = questions
            
        # Get degrees for potential dropdowns (standard fields)
        degrees = request.env['hr.recruitment.degree'].sudo().search([])

        return request.render("website_hr_recruitment.apply", {
            'job': job,
            'error': error,
            'default': default,
            # Custom form data
            'use_forms': job.use_forms,
            'form_questions': form_questions,
            'degrees': degrees,
            'main_object': job, 
        })


class WebsiteFormCustom(WebsiteForm):
    """Override standard WebsiteForm to prevent custom fields from dumping into Description."""

    def extract_data(self, model, values):
        # If we are submitting an application...
        if model.model == 'hr.applicant':
            # Identify keys that start with form_q_
            keys_to_remove = [k for k in values.keys() if k.startswith('form_q_')]
            
            # Remove them from 'values' so Odoo's standard controller 
            # does NOT see them and does NOT add them to the 'Description' field.
            # Note: They are still available in 'request.params' for our model to read.
            for key in keys_to_remove:
                if key in values:
                    del values[key]
                    
        return super(WebsiteFormCustom, self).extract_data(model, values)