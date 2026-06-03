# -*- coding: utf-8 -*-
"""Pre-migrate for 17.0.2.0.0 → 17.0.3.0.0 (Etap 3: recruiter cockpit).

Refresh the shipped call-invite template body to read
`object.booking_url` so manual "Send Email" actions also render the
button. Honours recruiter customisation via pristine-detection (same
pattern as v17.0.1.2.0 — see GUIDANCE).
"""
import logging
import re

_logger = logging.getLogger(__name__)


_OLD_BODY_V17_0_1_2_0 = """
<div style="margin:0px;padding:0px;font-size:14px;">
    <p>Hi <t t-out="object.partner_name or object.name or ''"/>,</p>
    <p>
        Thanks again for your interest in the
        <strong><t t-out="object.job_id.name or 'role'"/></strong>
        position. Please pick a slot that works for you:
    </p>
    <p t-if="ctx.get('booking_url')" style="margin:24px 0;">
        <a t-att-href="ctx.get('booking_url')"
           style="background:#714B67;color:#ffffff;padding:12px 22px;
                  border-radius:4px;text-decoration:none;
                  display:inline-block;font-weight:600;">
            Book a call
        </a>
    </p>
    <p>
        Looking forward to talking with you.
    </p>
    <p>
        Best,<br/>
        <t t-out="object.user_id.name or object.company_id.name or ''"/>
    </p>
</div>
"""


def _normalise(s):
    if not s:
        return ''
    return re.sub(r'\s+', ' ', s).strip()


def _body_strings(value):
    """Unwrap mail.template.body_html — JSONB dict in Odoo 17."""
    if value is None:
        return []
    if isinstance(value, dict):
        return [v for v in value.values() if v]
    return [value]


def migrate(cr, version):
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = 'hr_recruitment_call_stage'
           AND name   = 'mail_template_call_invite_generic'
           AND model  = 'mail.template'
        LIMIT 1
    """)
    row = cr.fetchone()
    if not row:
        return
    cr.execute(
        "SELECT body_html FROM mail_template WHERE id = %s",
        (row[0],),
    )
    body_row = cr.fetchone()
    if not body_row or not body_row[0]:
        return
    bodies = _body_strings(body_row[0])
    pristine_norm = _normalise(_OLD_BODY_V17_0_1_2_0)
    if not bodies or not all(_normalise(b) == pristine_norm for b in bodies):
        _logger.info(
            "hr_recruitment_call_stage 17.0.3.0.0: shipped template body "
            "was customised — preserved. Manual review may be needed to "
            "adopt `object.booking_url`.",
        )
        return
    cr.execute("""
        UPDATE ir_model_data
           SET noupdate = false
         WHERE module = 'hr_recruitment_call_stage'
           AND name   = 'mail_template_call_invite_generic'
    """)
    _logger.info(
        "hr_recruitment_call_stage 17.0.3.0.0: pristine template body — "
        "noupdate cleared so the new body XML loads in this upgrade.",
    )
