# -*- coding: utf-8 -*-
"""Post-migrate for 17.0.4.2.0 → 17.0.5.0.0.

Re-asserts `noupdate=True` on the canonical
`mail_template_call_invite_generic` record after the pre-migrate may
have cleared it. Mirrors the rest of `data/mail_template_data.xml`
(which carries `noupdate="1"` so future upgrades respect recruiter
edits).

Idempotent: setting `noupdate` to its already-True value is a no-op.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE ir_model_data
           SET noupdate = true
         WHERE module = 'hr_recruitment_call_stage'
           AND name   = 'mail_template_call_invite_generic'
           AND noupdate IS DISTINCT FROM true
        """
    )
    if cr.rowcount:
        _logger.info(
            "hr_recruitment_call_stage 17.0.5.0.0: re-asserted "
            "noupdate=True on the canonical call-invite template.",
        )
