# -*- coding: utf-8 -*-
from odoo import models, fields


class Student(models.Model):
    _name = 'gym.student'
    _description = 'Student'

    partner_id = fields.Many2one('res.partner', required=True)
    trainer_id = fields.Many2one('res.users', default=lambda self: self.env.user)
    
    name = fields.Char(string='Name', required=True)
    email = fields.Char(related='partner_id.email', store=True)
    phone = fields.Char(related='partner_id.phone', store=True)
    height = fields.Float(string="Height", required=True)
    weight = fields.Float(string="Weight", required=True)
    heardFrom = fields.Text(string="Heard from", help="From where did student hear about Fight Culture")
    prefferedSport = fields.Selection(selection=[
        ('boxing', 'Boxing'),
        ('muai_thai', 'Muai Thai'),
        ('kickboxing', 'Kickboxing'),
        ("functional", 'Functional training'),
        ("more_fights", "More fights")
    ], string='Preffered sport', default='boxing')
    classType = fields.Selection(selection=[
        ('group', "Group"), 
        ("private", "Private")
    ], string="Preffered class type")
    birthDay = fields.Date(string="Birthday", required=True)
    injuries = fields.Text(string="Injuries", help="Current student injuries (if exist)")
    goals = fields.Text(string="Goals", help="Training goals")
    noTrainingYears = fields.Integer(string="Years without training", help="For how many years student stopped training")
    otherSportExp = fields.Text(string="Experience in other sport")
    medicalRestrictions = fields.Text(string="Medical Restrictions")
