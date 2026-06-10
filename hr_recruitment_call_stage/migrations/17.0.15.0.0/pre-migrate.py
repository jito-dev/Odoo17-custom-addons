# -*- coding: utf-8 -*-
"""Migration 17.0.14.0.0 → 17.0.15.0.0 — drop the custom-booking-link fields.

The recruiter-pasted / per-stage custom booking URL feature has been
removed: the Appointments-minted ``appointment.invite.book_url`` is now
the single source of every Call Stage booking link. The two stored
columns that backed the old override are dropped here so they do not
linger as orphan columns after the field definitions disappear:

* ``hr_applicant.manual_meeting_url``  (was ``hr.applicant.manual_meeting_url``)
* ``hr_job_stage_config.default_meeting_url``
  (was ``hr.job.stage.config.default_meeting_url``)

Idempotent: ``DROP COLUMN IF EXISTS`` is a no-op when the column is
already gone (e.g. a DB that never carried the field, or a re-run).
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    for table, column in (
        ('hr_applicant', 'manual_meeting_url'),
        ('hr_job_stage_config', 'default_meeting_url'),
    ):
        cr.execute(
            "ALTER TABLE %s DROP COLUMN IF EXISTS %s" % (table, column)
        )
        _logger.info(
            "hr_recruitment_call_stage: dropped orphan column %s.%s",
            table, column,
        )
