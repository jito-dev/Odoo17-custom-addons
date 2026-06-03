# -*- coding: utf-8 -*-
"""Post-migrate 17.0.18.3.0 → 17.0.18.4.0.

Restyle the "Book a call" button in the call-invite email from the old
Odoo-purple (#714B67) to a minimalist soft-black (#1a1a1a).

The template data file is ``noupdate="1"``, so a plain ``-u`` does NOT
rewrite the live ``mail_template`` rows — this migration does it
directly.

Surgical, not a full-body rewrite (contrast v17.0.6.0.0's pre-migrate):
we regex-replace ONLY the button's old inline ``style`` block. Any body
where the recruiter has already changed the button style no longer
matches the pattern and is left untouched, so manual customisation is
preserved. Recruiter edits to the surrounding copy (greeting, sign-off)
are likewise untouched because we only rewrite the matched style run.

Scope: the canonical shipped template (resolved via ir_model_data) plus
every template referenced by an ``is_call_stage`` config — those are the
bodies a candidate actually receives.
"""
import logging
import re

from psycopg2.extras import Json

_logger = logging.getLogger(__name__)


# Old button style as shipped up to v17.0.18.3.0. ``\s*`` after each
# declaration tolerates the newline+indentation the XML stores between
# properties, and any whitespace reflow on duplicated templates.
_OLD_STYLE_RE = re.compile(
    r"background:#714B67;\s*color:#ffffff;\s*padding:12px 22px;\s*"
    r"border-radius:4px;\s*text-decoration:none;\s*"
    r"display:inline-block;\s*font-weight:600;\s*"
)

_NEW_STYLE = (
    "background:#1a1a1a;color:#ffffff;padding:12px 24px;"
    "border-radius:6px;text-decoration:none;"
    "display:inline-block;font-weight:500;letter-spacing:0.3px;"
)


def _restyle(value):
    """Return (new_jsonb_payload_or_None, changed). ``value`` is the raw
    ``body_html`` column — a per-language dict (jsonb) or, defensively, a
    plain string. Only languages whose body still carries the old button
    style are rewritten.
    """
    if isinstance(value, dict):
        new = dict(value)
        changed = False
        for lang, body in value.items():
            if body and _OLD_STYLE_RE.search(body):
                new[lang] = _OLD_STYLE_RE.sub(_NEW_STYLE, body)
                changed = True
        return (Json(new) if changed else None), changed
    if isinstance(value, str) and _OLD_STYLE_RE.search(value):
        return Json({'en_US': _OLD_STYLE_RE.sub(_NEW_STYLE, value)}), True
    return None, False


def _ids_to_restyle(cr):
    ids = set()
    cr.execute(
        """
        SELECT res_id FROM ir_model_data
         WHERE module = 'hr_recruitment_call_stage'
           AND name   = 'mail_template_call_invite_generic'
           AND model  = 'mail.template'
         LIMIT 1
        """
    )
    row = cr.fetchone()
    if row:
        ids.add(row[0])
    cr.execute(
        """
        SELECT DISTINCT mt.id
          FROM mail_template mt
          JOIN hr_job_stage_config cfg ON cfg.mail_template_id = mt.id
         WHERE cfg.is_call_stage = TRUE
        """
    )
    ids.update(r[0] for r in cr.fetchall())
    return ids


def migrate(cr, version):
    restyled, skipped = [], []
    for tmpl_id in _ids_to_restyle(cr):
        cr.execute(
            "SELECT body_html FROM mail_template WHERE id = %s", (tmpl_id,)
        )
        row = cr.fetchone()
        if not row:
            continue
        payload, changed = _restyle(row[0])
        if changed:
            cr.execute(
                "UPDATE mail_template SET body_html = %s WHERE id = %s",
                (payload, tmpl_id),
            )
            restyled.append(tmpl_id)
        else:
            skipped.append(tmpl_id)
    _logger.info(
        "hr_recruitment_call_stage 17.0.18.4.0: restyled 'Book a call' "
        "button to #1a1a1a on %d template(s) (ids=%s); left %d "
        "template(s) untouched — already customised (ids=%s).",
        len(restyled), restyled, len(skipped), skipped,
    )
