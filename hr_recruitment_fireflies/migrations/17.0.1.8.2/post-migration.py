# -*- coding: utf-8 -*-
"""Clear the auto-generated interview titles left behind by the old compute.

Up to 17.0.1.7.x the interview `name` was computed as "<Type label> - <candidate>"
(or just "<Type label>" when no candidate) and stored. From 17.0.1.8.0 the title is
no longer auto-filled — new interviews start empty with a placeholder hint. This
migration blanks ONLY the titles that still exactly match the old auto pattern for the
record's current type + candidate, so any title a recruiter typed by hand is preserved.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Interview = env['hr.applicant.interview']
    # interview_type is deprecated but still on the model, so its labels are available.
    type_labels = dict(Interview._fields['interview_type'].selection)

    interviews = Interview.search([('name', '!=', False)])
    cleared = 0
    for rec in interviews:
        label = type_labels.get(rec.interview_type, 'Interview')
        candidate = rec.applicant_id.partner_name or rec.applicant_id.display_name
        auto_name = ('%s - %s' % (label, candidate)) if candidate else label
        if rec.name == auto_name:
            rec.name = False
            cleared += 1

    _logger.info(
        "hr_recruitment_fireflies: cleared %s auto-generated interview title(s).",
        cleared,
    )
