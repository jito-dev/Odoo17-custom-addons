# -*- coding: utf-8 -*-
"""Pre-migrate 17.0.5.0.0 → 17.0.6.0.0.

The v17.0.5.0.0 sweeper relied on (a) the literal substring
``Booking link unavailable`` to find stale bodies, and (b) clearing
``ir_model_data.noupdate`` so the manifest data-file XML would reload
during upgrade. In the wild we observed installs where the canonical
template body still rendered the legacy fallback paragraph after
running ``-u hr_recruitment_call_stage`` — the noupdate trick did not
take effect. Root cause is unclear (Odoo upgrade ordering vs. our
migration phase), so this migration stops relying on it.

What this does — unconditionally, every upgrade to 17.0.6.0.0:

1. Force ``UPDATE mail_template SET body_html = <SHIPPED_BODY>`` on
   the canonical row (resolved via ir_model_data).
2. Force the same UPDATE on every mail.template referenced by a
   ``hr.job.stage.config`` row with ``is_call_stage = TRUE`` — those
   are the templates the candidate actually receives. Recruiter
   customisation is preserved only when the body has NEITHER the
   legacy ``Booking link unavailable`` marker NOR an empty/null
   ``object.booking_url`` button. In other words: if the template
   would render a broken button for a real candidate, we rewrite it.

The check is conservative — a recruiter who wrote their own body
with a properly-guarded ``object.booking_url`` button is left alone.
"""
import logging

from psycopg2.extras import Json

_logger = logging.getLogger(__name__)


_SHIPPED_BODY = """
<div style="margin:0px;padding:0px;font-size:14px;">
    <p>Hi <t t-out="object.partner_name or object.name or ''"/>,</p>
    <p>
        Thanks again for your interest in the
        <strong><t t-out="object.job_id.name or 'role'"/></strong>
        position. Please pick a slot that works for you:
    </p>
    <p t-if="ctx.get('booking_url') or object.booking_url" style="margin:24px 0;">
        <a t-att-href="ctx.get('booking_url') or object.booking_url"
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
""".strip()


def _body_strings(value):
    if value is None:
        return []
    if isinstance(value, dict):
        return [v for v in value.values() if v]
    return [value]


def _is_broken_body(value):
    """A body is "broken" if it carries the legacy fallback paragraph,
    OR it references ``ctx.get('booking_url')`` without the
    ``or object.booking_url`` companion (the manual-send code path
    never sets the context key, so such templates render a blank
    button area on manual send).
    """
    strings = _body_strings(value)
    if not strings:
        return True  # empty body — definitely cannot render a button
    for s in strings:
        if 'Booking link unavailable' in s:
            return True
        if "ctx.get('booking_url')" in s and 'object.booking_url' not in s:
            return True
    return False


def _refreshed_payload(existing, new_body):
    if isinstance(existing, dict) and existing:
        return Json({lang: new_body for lang in existing.keys()})
    return Json({'en_US': new_body})


def migrate(cr, version):
    # 1) Canonical row — always rewrite.
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
    canonical_id = row[0] if row else None
    if canonical_id:
        cr.execute(
            "SELECT body_html FROM mail_template WHERE id = %s",
            (canonical_id,),
        )
        body = cr.fetchone()[0]
        cr.execute(
            "UPDATE mail_template SET body_html = %s WHERE id = %s",
            (_refreshed_payload(body, _SHIPPED_BODY), canonical_id),
        )
        _logger.info(
            "hr_recruitment_call_stage 17.0.6.0.0: rewrote canonical "
            "template body (id=%s) to the v17.0.6 shipped body.",
            canonical_id,
        )

    # 2) Templates referenced by is_call_stage configs — rewrite if broken.
    cr.execute(
        """
        SELECT DISTINCT mt.id, mt.body_html
          FROM mail_template mt
          JOIN hr_job_stage_config cfg ON cfg.mail_template_id = mt.id
         WHERE cfg.is_call_stage = TRUE
           AND (%s IS NULL OR mt.id <> %s)
        """,
        (canonical_id, canonical_id),
    )
    candidates = cr.fetchall()
    refreshed_ids = []
    preserved_ids = []
    for tmpl_id, body in candidates:
        if _is_broken_body(body):
            cr.execute(
                "UPDATE mail_template SET body_html = %s WHERE id = %s",
                (_refreshed_payload(body, _SHIPPED_BODY), tmpl_id),
            )
            refreshed_ids.append(tmpl_id)
        else:
            preserved_ids.append(tmpl_id)
    _logger.info(
        "hr_recruitment_call_stage 17.0.6.0.0: rewrote %d broken "
        "duplicate/customised templates referenced by Call Stage "
        "configs (ids=%s); preserved %d well-formed customisations "
        "(ids=%s).",
        len(refreshed_ids), refreshed_ids,
        len(preserved_ids), preserved_ids,
    )
