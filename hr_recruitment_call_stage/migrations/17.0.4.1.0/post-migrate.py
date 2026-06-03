# -*- coding: utf-8 -*-
"""Hotfix 17.0.4.0.0 → 17.0.4.1.0.

The pristine-detection in the v17.0.1.2.0 and v17.0.3.0.0 pre-migrates
compared raw body_html source to a Python string constant; Odoo's HTML
field cleanup normalises whitespace and quote styles differently, so
the comparison silently never matched for some DBs. Result: the
"Booking link unavailable — please reply to this email" fallback
paragraph remained in production templates even after upgrade.

This hotfix surgically strips that paragraph using a regex that
matches BOTH em-dash and ASCII-hyphen variants. It preserves every
other customisation a recruiter may have applied — only the literal
fallback paragraph is removed.

Idempotent: a body that no longer contains "Booking link unavailable"
is left untouched.
"""
import logging
import re

_logger = logging.getLogger(__name__)


# Match the fallback paragraph as a whole, regardless of attribute
# ordering, exact whitespace, or em-dash vs hyphen. We do NOT try to
# parse the HTML — substring on "Booking link unavailable" is uniquely
# distinguishing enough that no other recruiter copy could match it.
_FALLBACK_RE = re.compile(
    r'<p[^>]*?(?:t-if|data-oe-t-if)="not ctx\.get\(\\?\'booking_url\\?\'\)".*?</p>',
    re.DOTALL | re.IGNORECASE,
)
_FALLBACK_TEXT_RE = re.compile(
    r'\(?\s*Booking link unavailable[\s\S]{0,300}?(?:schedule manually\.?)\)?',
    re.IGNORECASE,
)


def migrate(cr, version):
    cr.execute("""
        SELECT mt.id, mt.body_html
          FROM mail_template mt
          JOIN ir_model_data imd
            ON imd.res_id = mt.id
           AND imd.model  = 'mail.template'
         WHERE imd.module = 'hr_recruitment_call_stage'
           AND imd.name   = 'mail_template_call_invite_generic'
    """)
    rows = cr.fetchall()
    if not rows:
        _logger.info(
            "hr_recruitment_call_stage 17.0.4.1.0 hotfix: shipped "
            "template not present; nothing to strip.")
        return
    for tmpl_id, body in rows:
        if not body or 'Booking link unavailable' not in body:
            continue
        new_body = _FALLBACK_RE.sub('', body)
        if new_body == body:
            # The <p ... t-if=...> regex didn't match — fall back to a
            # textual match-and-strip of the surrounding paragraph.
            new_body = _FALLBACK_TEXT_RE.sub('', body)
            # Tidy: drop the now-empty <p>...</p> wrapper.
            new_body = re.sub(
                r'<p[^>]*>\s*</p>', '', new_body,
                flags=re.IGNORECASE)
        cr.execute(
            "UPDATE mail_template SET body_html = %s WHERE id = %s",
            (new_body, tmpl_id),
        )
        _logger.info(
            "hr_recruitment_call_stage 17.0.4.1.0 hotfix: stripped "
            "fallback paragraph from mail_template id=%s.", tmpl_id,
        )
