# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request
from odoo.addons.website.controllers.form import WebsiteForm
from odoo.addons.website_hr_recruitment.controllers.main import WebsiteHrRecruitment

_logger = logging.getLogger(__name__)


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
        error = {}
        default = {}
        if 'website_hr_recruitment_error' in request.session:
            error = request.session.pop('website_hr_recruitment_error')
            default = request.session.pop('website_hr_recruitment_default')

        form_questions = False
        # Use sudo() to ensure we can read the 'use_forms' field and questions 
        # even if the public user has restricted access rules on hr.job
        if job.sudo().use_forms:
            questions = job.sudo().get_form_questions()
            if questions:
                form_questions = questions
            
        degrees = request.env['hr.recruitment.degree'].sudo().search([])

        return request.render("website_hr_recruitment.apply", {
            'job': job,
            'error': error,
            'default': default,
            'use_forms': job.sudo().use_forms,
            'form_questions': form_questions,
            'degrees': degrees,
            'main_object': job, 
        })


class WebsiteFormCustom(WebsiteForm):
    """Override standard WebsiteForm to prevent custom fields from dumping into Description."""

    @http.route('/website/form/<string:model_name>', type='http', auth="public", methods=['POST'], website=True)
    def website_form(self, model_name, **kwargs):
        return super(WebsiteFormCustom, self).website_form(model_name, **kwargs)

    def extract_data(self, model, values):
        if model.model == 'hr.applicant':
            # Always copy 'values' before modification.
            # In some contexts, 'values' IS request.params. Modifying it in place
            # deletes the data globally, making it unavailable for insert_record.
            values = values.copy() 
            
            keys_to_remove = [k for k in values.keys() if k.startswith('form_q_')]
            for key in keys_to_remove:
                if key in values:
                    del values[key]
        return super(WebsiteFormCustom, self).extract_data(model, values)

    def insert_record(self, request, model, values, custom, meta=None):
        res_id = super(WebsiteFormCustom, self).insert_record(request, model, values, custom, meta=meta)
        
        if model.model == 'hr.applicant' and res_id:
            # Use request.httprequest.values
            # This is the raw Werkzeug combined dict (GET/POST) and is immutable/raw.
            # It bypasses any 'params' cleaning done by Odoo's extract_data or other modules.
            raw_data = request.httprequest.values
            
            form_answers = {}
            for k in raw_data.keys():
                if k.startswith('form_q_'):
                    val = raw_data.get(k)
                    form_answers[k] = val
            
            if form_answers:
                try:
                    # Clean the keys (remove 'form_q_')
                    cleaned_answers = {k.replace('form_q_', ''): v for k, v in form_answers.items()}
                    
                    applicant = request.env['hr.applicant'].sudo().browse(res_id)
                    if applicant.job_id and applicant.job_id.use_forms:
                        questions = applicant.job_id.sudo().get_form_questions()
                        applicant._create_form_response(cleaned_answers, questions)
                except Exception as e:
                    _logger.error(f"Failed to save form answers: {str(e)}")

        return res_id