# -*- coding: utf-8 -*-
from odoo import models, fields


class Student(models.Model):
    _name = 'gym.student'
    _description = 'Student'

    trainer_id = fields.Many2one('res.users', default=lambda self: self.env.user)
    name = fields.Char(string='Name', required=True)
    birthDay = fields.Date(string="Birthday", required=True)
    injuries = fields.Text(string="Injuries", help="Current student injuries (if exist)")
    goals = fields.Text(string="Goals", help="Training goals")
    noTrainingYears = fields.Integer(string="Years without training", help="For how many years student stopped training")
    otherSportExp = fields.Text(string="Experience in other sport")
    medicalRestrictions = fields.Text(string="Medical Restrictions")
