# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    fireflies_autopilot = fields.Boolean(
        string="Fireflies Autopilot",
        default=False,
        help="When on, Fireflies interviews run hands-free for this company:\n"
             "• a draft interview (pre-filled with the stage's questions) is "
             "auto-created when a candidate enters a stage that has interview "
             "questions;\n"
             "• pasting a Fireflies link auto-runs the analysis (the transcript "
             "is still fetched only once and cached);\n"
             "• the seeded questions are auto-answered right after the summary.\n"
             "Off by default so nothing runs unexpectedly (e.g. on production).",
    )
