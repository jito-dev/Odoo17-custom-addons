# -*- coding: utf-8 -*-
"""v17.0.2.0.0 — clear the backlog of cancellation to-dos that were never true.

Until this version a cancelled booking raised a `mail.activity` immediately,
through the helper built for configuration failures — so it arrived titled
*Fix Call Stage booking link* even though no link had broken. And because a
reschedule on the portal is physically a cancel followed by a rebooking, the
alert fired for candidates who had merely moved their slot: of the nine
applicants that ever raised it, six had rescheduled.

Those to-dos are still sitting open in recruiters' lists. This pass closes the
ones that are demonstrably false — the applicant has a live booked call right
now — and adopts the rest, linking them to `call_cancel_activity_id` so that a
late rebooking can retract them the way new ones are retracted.

Deliberately NOT touched:

* activities already closed by hand — the history stays as it happened;
* `call_cancelled` flags without a `call_cancel_at`, which is every row
  written before this version. The sweep's domain requires that timestamp, so
  old cancellations cannot produce a retroactive wave of new to-dos. A
  cancellation from last month gets its verdict from the recruiter, not from
  a cron waking up after the upgrade.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

LEGACY_SUMMARY = 'Fix Call Stage booking link'
LEGACY_NOTE_MARKER = 'Call cancelled for applicant'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    activities = env['mail.activity'].search([
        ('res_model', '=', 'hr.applicant'),
        ('summary', '=', LEGACY_SUMMARY),
        ('note', 'ilike', LEGACY_NOTE_MARKER),
    ])
    if not activities:
        _logger.info(
            "hr_recruitment_call_stage_google_meet: no legacy cancellation "
            "to-dos to clear.")
        return

    Applicant = env['hr.applicant'].with_context(active_test=False)
    closed = adopted = 0
    for activity in activities:
        applicant = Applicant.browse(activity.res_id).exists()
        if not applicant:
            continue
        if applicant._get_booked_call_event():
            # The candidate is booked right now, so this to-do was raised for a
            # reschedule. Closed rather than deleted: it did exist, somebody may
            # have looked at it, and the feedback line explains itself.
            activity.action_feedback(feedback=(
                "Closed automatically: the candidate has a live booking, so "
                "this was a reschedule rather than a cancellation."
            ))
            closed += 1
        elif not applicant.call_cancel_activity_id:
            # A genuine open cancellation. Adopt it so a late rebooking closes
            # this one instead of leaving it orphaned beside a new to-do.
            applicant.call_cancel_activity_id = activity.id
            adopted += 1

    _logger.info(
        "hr_recruitment_call_stage_google_meet: legacy cancellation to-dos — "
        "%s closed as false alarms, %s adopted as genuine, out of %s found.",
        closed, adopted, len(activities))
