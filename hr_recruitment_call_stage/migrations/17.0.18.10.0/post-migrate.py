# -*- coding: utf-8 -*-
"""Post-migrate → 17.0.18.10.0.

Recolour the "Book a call" button in the call-invite email to the company
PRIMARY brand colour (#000000) and add an explicit ``background-color``
declaration next to the ``background`` shorthand.

Why both declarations: some email clients (Outlook, parts of Gmail) strip
the ``background`` shorthand on ``<a>`` elements, which rendered the button
transparent — the candidate could not see it. ``background-color`` is the
robust, widely honoured declaration; we keep ``background`` too for clients
that only read the shorthand.

The template data file is ``noupdate="1"``, so a plain ``-u`` does NOT
rewrite the live ``mail_template`` rows — this migration does it directly
(same approach as 17.0.18.4.0's post-migrate).

Robust across prior states: the button background may currently be the
soft-black ``#1a1a1a`` (shipped in 17.0.18.4.0), the older Odoo-purple, the
editor-expanded longhand form, or the original dynamic
``{{ email_secondary_color }}`` expression. We anchor on the button's own
signature (``color:#ffffff`` immediately followed by ``padding:12px 2Npx``
and ``border-radius:[46]px``) and rewrite ONLY the leading ``background*``
run, normalising any of those to the primary colour. A body where the
recruiter changed the button's padding/border-radius (i.e. genuinely
restyled it) no longer matches and is left untouched, so deliberate
customisation is preserved.
"""
import logging
import re

from psycopg2.extras import Json

_logger = logging.getLogger(__name__)


# Match the run of one-or-more ``background*`` declarations that directly
# precede the button's ``color:#ffffff; padding:12px 2Npx; border-radius:..``
# signature. ``[^:]*`` after ``background`` covers ``background``,
# ``background-color`` and the editor-expanded ``background-clip`` etc.;
# ``[^;]*`` for the value tolerates a static hex OR a ``{{ ... }}`` QWeb
# expression. ``\s*`` absorbs the newline+indent the XML may store.
_BUTTON_BG_RE = re.compile(
    r"(?:background[^:]*:[^;]*;\s*)+"
    r"(?=color:#ffffff;\s*padding:12px 2[024]px;\s*border-radius:[46]px;)"
)

# Primary brand colour, ``background-color`` first (robust) then the
# shorthand (for shorthand-only clients).
_NEW_BG = "background-color:#000000;background:#000000;"


def _restyle(value):
    """Return ``(jsonb_payload_or_None, changed)``.

    ``value`` is the raw ``body_html`` column — a per-language dict (jsonb)
    or, defensively, a plain string. Only languages whose body still carries
    a button-background run are rewritten.
    """
    if isinstance(value, dict):
        new = dict(value)
        changed = False
        for lang, body in value.items():
            if body and _BUTTON_BG_RE.search(body):
                new[lang] = _BUTTON_BG_RE.sub(_NEW_BG, body)
                changed = True
        return (Json(new) if changed else None), changed
    if isinstance(value, str) and _BUTTON_BG_RE.search(value):
        return Json({'en_US': _BUTTON_BG_RE.sub(_NEW_BG, value)}), True
    return None, False


def _ids_to_restyle(cr):
    """The canonical shipped template plus every template a candidate can
    actually receive (those wired to an ``is_call_stage`` config)."""
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
        "hr_recruitment_call_stage 17.0.18.10.0: recoloured 'Book a call' "
        "button to primary #000000 (with background-color fallback) on %d "
        "template(s) (ids=%s); left %d untouched — no matching button run "
        "(ids=%s).",
        len(restyled), restyled, len(skipped), skipped,
    )
