from odoo import api, SUPERUSER_ID

def post_init_hook(env):
    create_questions(env)

def create_questions(env):
    """ Creates questions independently. Then links to Main Survey if exists """
    Survey = env['iq.survey'].sudo()
    
    # 2. Answer Key
    CORRECT_ANSWERS_LIST = [
        4, 5, 1, 2, 6, 3, 6, 2, 1, 3, 4, 5,  # A
        2, 6, 1, 2, 1, 3, 5, 6, 4, 3, 4, 5,  # B
        8, 2, 3, 8, 7, 4, 5, 1, 7, 6, 1, 2,  # C
        3, 4, 3, 7, 8, 6, 5, 4, 1, 2, 5, 6,  # D
        7, 6, 8, 2, 1, 5, 1, 6, 3, 2, 4, 5   # E
    ]

    SECTIONS_CONFIG = [
        {'code': 'A', 'options': 6},
        {'code': 'B', 'options': 6},
        {'code': 'C', 'options': 8},
        {'code': 'D', 'options': 8},
        {'code': 'E', 'options': 8},
    ]

    Question = env['iq.question'].sudo()
    global_index = 0
    all_questions = []
    
    for section_data in SECTIONS_CONFIG:
        section_code = section_data['code']
        num_options = section_data['options']
        
        for i in range(1, 13):
            if global_index >= len(CORRECT_ANSWERS_LIST): break
                
            q_code = f"{section_code}-{i}"
            correct_val = CORRECT_ANSWERS_LIST[global_index]
            
            # Check if exists
            q = Question.search([('title', '=', q_code)], limit=1)
            if not q:
                q = Question.create({
                    'title': q_code,
                    'sequence': global_index + 1,
                    'image_filename': f"{q_code}.png",
                    'correct_answer': correct_val,
                    'num_options': num_options
                })
            all_questions.append(q.id)
            global_index += 1

    # Link to Main Survey if exists
    survey = env.ref('iq_tests_survey.main_iq_test', raise_if_not_found=False)
    if survey:
        survey.write({'question_ids': [(6, 0, all_questions)]})