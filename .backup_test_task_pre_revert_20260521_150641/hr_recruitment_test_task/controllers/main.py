from odoo import http, fields
from odoo.http import request

class TestTaskController(http.Controller):

    @http.route('/test-task/start', type='http', auth='public', website=True)
    def test_task_start(self, token=None, **kwargs):
        if not token:
            return request.render('website.http_error', {'status_code': 400, 'status_message': "Invalid Access: No token provided."})
        
        # Find Applicant by Token
        Applicant = request.env['hr.applicant'].sudo()
        applicant = Applicant.search([('test_task_token', '=', token)], limit=1)
        
        if not applicant:
            return request.render('website.http_error', {'status_code': 404, 'status_message': "Invalid Access: Token not found or expired."})

        # Render the form
        return request.render('hr_recruitment_test_task.template_test_submission', {
            'applicant': applicant,
            'token': token,
            'previous_submissions': applicant.submission_ids
        })

    @http.route('/test-task/submit', type='http', auth='public', methods=['POST'], website=True)
    def test_task_submit(self, token, github_link, additional_info=None, **kwargs):
        Applicant = request.env['hr.applicant'].sudo()
        applicant = Applicant.search([('test_task_token', '=', token)], limit=1)
        
        if not applicant:
            return "Error: Applicant not found."

        # 1. Create Submission Record
        new_version = len(applicant.submission_ids) + 1
        
        request.env['hr.test.submission'].sudo().create({
            'applicant_id': applicant.id,
            'github_link': github_link,
            'additional_info': additional_info,
            'version': new_version
        })

        # 2. Move to "Test Task Submitted" Stage
        # CRITICAL FIX: Search for stage belonging to THIS JOB specifically
        submitted_stage = request.env['hr.recruitment.stage'].sudo().search([
            ('name', 'ilike', 'Test Task Submitted'),
            '|',
            ('job_ids', '=', False),                 # Matches global stages
            ('job_ids', 'in', [applicant.job_id.id]) # Matches stages for this job
        ], limit=1)
        
        if submitted_stage and applicant.stage_id != submitted_stage:
            applicant.write({'stage_id': submitted_stage.id})
            
            # Log a note on the chatter
            applicant.message_post(
                body=f"Candidate submitted test task (v{new_version}). Link: {github_link}",
                subtype_id=request.env.ref('mail.mt_note').id
            )

        return request.render('hr_recruitment_test_task.template_thank_you')