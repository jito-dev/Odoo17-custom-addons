# -*- coding: utf-8 -*-
"""Post-migrate for 17.0.2.0.0 → 17.0.3.0.0 (Etap 3).

Re-assert noupdate=true on the shipped template after pre-migrate
temporarily cleared it.
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
