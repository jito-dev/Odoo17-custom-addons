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

    fireflies_transcript_retention_days = fields.Integer(
        string="Transcript Retention (days)",
        default=30,
        help="GDPR data minimization: a daily job clears the stored raw "
             "interview transcript this many days after it was last analyzed. "
             "The AI summary, recruiter note and answered questions are kept; "
             "only the heavy transcript text is removed. A purged interview is "
             "simply re-fetched from Fireflies if it is ever re-analyzed. "
             "Set to 0 to disable retention (keep transcripts indefinitely).",
    )
