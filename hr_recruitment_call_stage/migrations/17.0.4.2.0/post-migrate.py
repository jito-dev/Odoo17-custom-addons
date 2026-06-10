# -*- coding: utf-8 -*-
"""Post-migrate for 17.0.4.1.0 → 17.0.4.2.0.

Re-assert `noupdate=true` on the shipped call-invite template so future
upgrades fall through the same pristine-detection gate rather than
trampling recruiter edits made after this upgrade.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE ir_model_data
           SET noupdate = true
         WHERE module = 'hr_recruitment_call_stage'
           AND name   = 'mail_template_call_invite_generic'
    """)
    _logger.info(
        "hr_recruitment_call_stage 17.0.4.2.0: noupdate=true re-asserted "
        "on shipped call-invite template.")
