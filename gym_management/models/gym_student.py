# -*- coding: utf-8 -*-
from odoo import models, fields


class Student(models.Model):
    _inherit = "res.partner"

    trainer_id = fields.Many2one('res.users', string="Trainer")

    height = fields.Float(string="Height (cm)")
    weight = fields.Float(string="Weight (kg)")
    heardFrom = fields.Text(string="Heard from", help="From where did student hear about Fight Culture")
    prefferedSport = fields.Selection(selection=[
        ('boxing', 'Boxing'),
        ('muai_thai', 'Muai Thai'),
        ('kickboxing', 'Kickboxing'),
        ("functional", 'Functional training'),
        ("more_fights", "More fights")
    ], string='Preferred sport', default='boxing')
    classType = fields.Selection(selection=[
        ('group', "Group"),
        ("private", "Private")
    ], string="Class type")
    birthDay = fields.Date(string="Birthday")
    injuries = fields.Text(string="Injuries", help="Current student injuries (if any)")
    goals = fields.Text(string="Goals", help="Training goals")
    noTrainingYears = fields.Integer(string="Years without training", help="For how many years student stopped training")
    otherSportExp = fields.Text(string="Experience in other sport")
    medicalRestrictions = fields.Text(string="Medical Restrictions")
