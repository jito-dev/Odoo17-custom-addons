from odoo import http, fields
from odoo.http import request
import json


class MockSession:
    """ Simulate a result record for the preview """
    def __init__(self, survey):
        self.survey_id = survey
        self.name = "Candidate Name"
        self.iq_score = 125
        self.raw_score = 52
        self.test_duration = 18.5
        self.iq_category = "Superior"
        self.applicant_id = True
        self.create_date = fields.Datetime.now()


class IqTestController(http.Controller):

    # 1. Entry Point
    @http.route(['/iq-test', '/iq-test/go/<string:slug>'], type='http', auth='public', website=True)
    def start_page(self, slug=None, token=None, etoken=None, **kwargs):
        Survey = request.env['iq.survey'].sudo()
        if slug:
            survey = Survey.search([('slug', '=', slug)], limit=1)
        else:
            survey = request.env.ref('iq_tests_survey.main_iq_test', raise_if_not_found=False)
            if not survey:
                survey = Survey.search([], limit=1)

        if not survey:
            return "Error: Survey not found."

        values = {'survey': survey, 'token': token, 'etoken': etoken, 'error_msg': None}

        if token:
            # Recruitment / applicant flow (existing)
            Applicant = request.env['hr.applicant'].sudo()
            applicant = Applicant.search([('iq_access_token', '=', token)], limit=1)

            if not applicant:
                values['error_msg'] = "Invalid Access Token."
            elif applicant.iq_input_id:
                values['error_msg'] = "You have already completed this test."
                values['hide_form'] = True
            else:
                values['default_name'] = applicant.partner_name
                values['readonly_name'] = True

        elif etoken:
            # Employee campaign flow (new)
            UserInput = request.env['iq.user_input'].sudo()
            user_input = UserInput.search([
                ('access_token', '=', etoken),
                ('survey_id', '=', survey.id),
            ], limit=1)

            if not user_input:
                values['error_msg'] = "Invalid or expired access link."
                values['hide_form'] = True
            elif user_input.state == 'done':
                values['error_msg'] = "You have already completed this test."
                values['hide_form'] = True
            else:
                values['default_name'] = user_input.employee_id.name or user_input.name
                values['readonly_name'] = True

        elif survey.access_mode == 'email':
            values['ask_email'] = True
        elif survey.access_mode == 'token':
            values['error_msg'] = "This test requires a valid access link."
            values['hide_form'] = True
        elif survey.access_mode == 'internal':
            values['error_msg'] = "This test requires an access link. Please start it from the IQ Tests menu in the backend."
            values['hide_form'] = True

        return request.render('iq_tests_survey.template_start', values)

    # 2. Intro
    @http.route('/iq-test/intro', type='http', auth='public', website=True, methods=['POST'])
    def intro_page(self, survey_id, name, age, email=None, token=None, etoken=None, **kwargs):
        return request.render('iq_tests_survey.template_intro', {
            'survey_id': survey_id, 'name': name, 'age': age,
            'email': email, 'token': token, 'etoken': etoken,
        })

    # 3. Run
    @http.route('/iq-test/run', type='http', auth='public', website=True, methods=['POST'])
    def run_test(self, survey_id, name, age, email=None, token=None, etoken=None, **kwargs):
        try:
            age_int = int(age) if age else 0
            survey_id = int(survey_id)
        except Exception:
            return "Invalid parameters."

        Survey = request.env['iq.survey'].sudo()
        survey = Survey.browse(survey_id)
        Applicant = request.env['hr.applicant'].sudo()
        applicant = None
        user_input_record = None

        if token:
            # Existing recruitment flow
            applicant = Applicant.search([('iq_access_token', '=', token)], limit=1)
            if not applicant:
                return "Invalid Token"
            if applicant.iq_input_id:
                return "Test already taken."

        elif etoken:
            # Employee campaign flow
            UserInput = request.env['iq.user_input'].sudo()
            user_input_record = UserInput.search([
                ('access_token', '=', etoken),
                ('survey_id', '=', survey.id),
            ], limit=1)
            if not user_input_record:
                return "Invalid access link."
            if user_input_record.state == 'done':
                return "You have already completed this test."

        elif survey.access_mode == 'email' and email:
            if survey.job_id:
                domain = [('email_from', 'ilike', email), ('job_id', '=', survey.job_id.id)]
                applicant_list = Applicant.search(domain, order='id desc')
                if not applicant_list:
                    return "No application found for this email on this job position."
                applicant = applicant_list[0]
                if applicant.iq_input_id:
                    return "Test already taken."
            else:
                existing_result = request.env['iq.user_input'].sudo().search([
                    ('survey_id', '=', survey.id),
                    ('email', '=ilike', email)
                ], limit=1)
                if existing_result:
                    return "You have already completed this test with this email."

        questions = survey.question_ids.sorted('sequence')
        if not questions:
            return "Error: No questions."

        tasks_data = []
        for q in questions:
            tasks_data.append({
                'id': q.id, 'code': q.title,
                'image': f"/iq_tests_survey/static/src/img/tasks/{q.image_filename}",
                'options': q.num_options
            })

        return request.render('iq_tests_survey.template_run', {
            'name': name, 'age': age_int, 'email': email, 'token': token,
            'etoken': etoken,
            'tasks_json': json.dumps(tasks_data),
            'survey_id': survey.id,
            'applicant_id': applicant.id if applicant else None,
            'user_input_id': user_input_record.id if user_input_record else None,
        })

    # 4. Submit
    @http.route('/iq-test/submit', type='json', auth='public', methods=['POST'], cors='*')
    def submit_test(self, survey_id, name, age, answers, duration=0,
                    applicant_id=None, email=None, user_input_id=None, etoken=None):
        UserInput = request.env['iq.user_input'].sudo()
        Survey = request.env['iq.survey'].sudo().browse(int(survey_id))

        if user_input_id:
            # Employee campaign flow: update the existing pending record
            session = UserInput.browse(int(user_input_id))
            if not session.exists():
                return {'error': {'message': 'Invalid session.'}}
            if session.state == 'done':
                return {'error': {'message': 'Test already completed.'}}
            # Security: validate that the etoken matches the record
            if etoken and session.access_token != etoken:
                return {'error': {'message': 'Access token mismatch.'}}

            duration_minutes = float(duration) / 60.0
            session.write({
                'name': name,
                'age': int(age) if age else 0,
                'test_duration': duration_minutes,
            })

        else:
            # Existing applicant / email flow
            if applicant_id:
                Applicant = request.env['hr.applicant'].sudo()
                app = Applicant.browse(int(applicant_id))
                if app.iq_input_id:
                    return {'error': {'message': 'Test already taken.'}}
            elif email and not Survey.job_id:
                existing_result = UserInput.search([
                    ('survey_id', '=', int(survey_id)),
                    ('email', '=ilike', email)
                ], limit=1)
                if existing_result:
                    return {'error': {'message': 'Test already taken.'}}

            duration_minutes = float(duration) / 60.0
            session = UserInput.create({
                'survey_id': int(survey_id),
                'name': name, 'age': int(age) if age else 0, 'email': email,
                'test_duration': duration_minutes,
                'applicant_id': int(applicant_id) if applicant_id else False
            })

        AnswerLine = request.env['iq.user_input.line'].sudo()
        lines = []
        for q_id, opt in answers.items():
            try:
                lines.append({
                    'user_input_id': session.id,
                    'question_id': int(q_id),
                    'selected_option': int(opt)
                })
            except Exception:
                continue
        if lines:
            AnswerLine.create(lines)

        session.calculate_score()
        return {'redirect_url': f"/iq-test/result/{session.id}"}

    @http.route('/iq-test/result/<model("iq.user_input"):session>', type='http', auth='public', website=True)
    def result_page(self, session, **kwargs):
        return request.render('iq_tests_survey.template_result', {'session': session})

    # Preview for recruiter
    @http.route('/iq-test/preview/<model("iq.survey"):survey>', type='http', auth='user', website=True)
    def preview_result(self, survey, **kwargs):
        """ Renders the result template with dummy data for the recruiter """
        session = MockSession(survey)
        return request.render('iq_tests_survey.template_result', {'session': session})
