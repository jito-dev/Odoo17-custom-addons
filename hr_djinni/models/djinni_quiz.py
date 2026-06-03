# Copyright © 2024 Garazd Creation (https://garazd.biz)
# @author: Yurii Razumovskyi (support@garazd.biz)
# @author: Iryna Razumovska (support@garazd.biz)
# License OPL-1 (https://www.odoo.com/documentation/17.0/legal/licenses.html).

from odoo import api, fields, models


class DjinniQuiz(models.Model):
    _name = "djinni.quiz"
    _description = 'Djinni Quizzes'

    name = fields.Char(size=256)
    ref = fields.Char(readonly=True)
    active_until = fields.Datetime()
    job_id = fields.Many2one(
        comodel_name='hr.job',
        string='Vacancy',
    )
    question_ids = fields.One2many(
        comodel_name='djinni.quiz.question',
        inverse_name='quiz_id',
        string='Questions',
    )

    @api.constrains('job_id')
    def _check_job_id(self):
        for rec in self:
            if rec.job_id:
                rec.job_id.write({'djinni_quiz_id': rec.id})

    def prepare_json(self):
        self.ensure_one()
        return {
            'name': self.name,
            'active_until': self.active_until or None,
        }

    def create_quiz(self):
        """ Request to create quiz for vacancy """
        self.ensure_one()
        response = self.env['djinni.account']._djinni_api_request(
            account_ref=self.job_id.djinni_account_id.id,
            method='POST',
            json=self.prepare_json(),
            endpoint=f'/jobs/{self.job_id.djinni_ref}/quizzes/',
        )
        self.update({'ref': response['id']})

    def update_quiz(self):
        """ Request to update quiz for vacancy """
        self.ensure_one()
        response = self.env['djinni.account']._djinni_api_request(
            account_ref=self.job_id.djinni_account_id.id,
            method='PUT',
            json=self.prepare_json(),
            endpoint=f'/jobs/{self.job_id.djinni_ref}/quizzes/{self.ref}',
        )
        self.update({'ref': response['id']})

    def create_questions(self):
        """ Request to create questions for vacancy """
        self.ensure_one()
        for question in self.question_ids:
            response = self.env['djinni.account']._djinni_api_request(
                account_ref=self.job_id.djinni_account_id.id,
                method='POST',
                json=question.prepare_json(),
                endpoint=f'/jobs/{self.job_id.djinni_ref}/quizzes/{self.ref}/questions/',
            )
            question.update({'ref': response['id']})

    def update_questions(self):
        """ Request to update questions for vacancy """
        self.ensure_one()
        for question in self.question_ids:
            response = self.env['djinni.account']._djinni_api_request(
                account_ref=self.job_id.djinni_account_id.id,
                method='PUT',
                json=question.prepare_json(),
                endpoint=f'/jobs/{self.job_id.djinni_ref}/quizzes/{self.ref}/questions/{question.ref}',
            )
            question.update({'ref': response['id']})
