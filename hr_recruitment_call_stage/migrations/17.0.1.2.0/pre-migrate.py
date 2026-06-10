# -*- coding: utf-8 -*-
"""Pre-migrate for 17.0.1.1.0 → 17.0.1.2.0.

Idempotent. Additive only.

1. Composite index ``(job_id, stage_id, is_call_stage)`` on
   ``hr_job_stage_config`` — speeds up the per-booking config lookup in
   ``_call_stage_auto_advance_applicant``. Pre-stage so the freshly-loaded
   models can rely on it; failing fast here is fine since the table is
   small.

2. Refresh the shipped call-invite template body to the v17.0.1.2.0
   version (no "Booking link unavailable" fallback paragraph). Honours
   recruiter customisation: we ONLY overwrite a row whose current body
   matches the v17.0.1.1.0 shipped body byte-for-byte (after whitespace
   normalisation). Any custom edit — even a single typo fix — is left
   untouched.
"""
import logging
import re

_logger = logging.getLogger(__name__)


_OLD_BODY_V17_0_1_1_0 = """
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
    <p t-if="not ctx.get('booking_url')" style="color:#888;">
        (Booking link unavailable - please reply to this email and we
        will schedule manually.)
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

# Two variants because the XML source uses an em-dash but rendered HTML
# in some Odoo versions may have normalised it. Be permissive on read.
_OLD_BODY_EM_DASH = _OLD_BODY_V17_0_1_1_0.replace(
    "link unavailable - please",
    "link unavailable — please",
)


def _normalise(s):
    """Whitespace-normalise for safe equality."""
    if not s:
        return ''
    return re.sub(r'\s+', ' ', s).strip()


def _body_strings(value):
    """Yield body strings from a mail.template.body_html column value.

    In Odoo 17 translatable fields are stored as JSONB dicts keyed by
    lang (e.g. ``{'en_US': '<div>...</div>'}``). Older rows / non-trans
    columns may still come back as plain strings. Normalise both shapes
    to a list of strings so the caller can compare each translation
    against the shipped-body candidates.
    """
    if value is None:
        return []
    if isinstance(value, dict):
        return [v for v in value.values() if v]
    return [value]


def migrate(cr, version):
    # ---- 1. Composite index ------------------------------------------
    cr.execute("""
        CREATE INDEX IF NOT EXISTS
            hr_job_stage_config_call_lookup_idx
        ON hr_job_stage_config (job_id, stage_id, is_call_stage)
    """)
    _logger.info(
        "hr_recruitment_call_stage 17.0.1.2.0: composite call-lookup "
        "index ensured on hr_job_stage_config.",
    )

    # ---- 2. Refresh shipped template body if untouched ---------------
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = 'hr_recruitment_call_stage'
           AND name   = 'mail_template_call_invite_generic'
           AND model  = 'mail.template'
        LIMIT 1
    """)
    row = cr.fetchone()
    if not row:
        _logger.info(
            "hr_recruitment_call_stage 17.0.1.2.0: shipped template not "
            "found (fresh install path?); nothing to refresh.",
        )
        return
    tmpl_id = row[0]
    cr.execute(
        "SELECT body_html FROM mail_template WHERE id = %s",
        (tmpl_id,),
    )
    body_row = cr.fetchone()
    if not body_row or not body_row[0]:
        return
    bodies = _body_strings(body_row[0])
    if not bodies:
        return
    candidates = {
        _normalise(_OLD_BODY_V17_0_1_1_0),
        _normalise(_OLD_BODY_EM_DASH),
    }
    # All stored translations must match a shipped candidate; if any
    # diverges, recruiter has customised at least one language — leave
    # the row untouched.
    if not all(_normalise(b) in candidates for b in bodies):
        _logger.info(
            "hr_recruitment_call_stage 17.0.1.2.0: shipped template body "
            "was customised by the recruiter — preserved as-is. Manual "
            "review may be needed to remove the fallback paragraph.",
        )
        return
    # Match — safe to swap. The actual new body is loaded by Odoo from
    # the updated data XML during the post-load phase, so we don't
    # rewrite it here; we just signal the data layer to take over by
    # clearing the `noupdate` flag on this single row for the duration
    # of the upgrade.
    cr.execute("""
        UPDATE ir_model_data
           SET noupdate = false
         WHERE module = 'hr_recruitment_call_stage'
           AND name   = 'mail_template_call_invite_generic'
    """)
    _logger.info(
        "hr_recruitment_call_stage 17.0.1.2.0: shipped template body is "
        "pristine — noupdate cleared so the new XML body loads in this "
        "upgrade. Post-migrate re-asserts noupdate.",
    )
