# -*- coding: utf-8 -*-
"""Pre-migrate for 17.0.4.2.0 → 17.0.5.0.0 (Etap 6: stale body sweeper).

Earlier pre-migrates (17.0.1.2.0, 17.0.3.0.0, 17.0.4.2.0) refresh the
shipped call-invite body only when the DB row byte-matches a known
shipped variant after whitespace-normalisation. That covers a pristine
install but misses:

- Bodies that picked up a stray whitespace edit (e.g. recruiter opened
  the WYSIWYG editor and saved without changing content) — Odoo's HTML
  field cleanup re-emits attributes, defeating the strict match.
- Recruiter duplicates (role-specific variants — Designer / Engineer /
  Sales — see GUIDANCE). Duplicates live under their own ir_model_data
  row (or none at all), so the canonical-only refresh path never sees
  them.

Net effect on those installs: the DB body still reads ONLY
`ctx.get('booking_url')` (no `or object.booking_url` fallback), so
manual "Send Email" and the chatter composer render an empty button and
— for the very oldest 17.0.1.1.0 body — show the embarrassing
"(Booking link unavailable — please reply…)" paragraph to candidates.

This migration sweeps EVERY mail.template whose body still contains the
literal substring `Booking link unavailable` and rewrites it to the
current shipped body. The canonical row additionally gets
`noupdate=False` so the XML in `data/mail_template_data.xml` reloads
cleanly during this upgrade. Bodies without the legacy marker are
preserved (recruiter customisation wins — see [[etap6_body_refresh]]).

Idempotent: re-running finds no rows with the marker and is a no-op.
"""
import logging

from psycopg2.extras import Json

_logger = logging.getLogger(__name__)


# Keep in lock-step with data/mail_template_data.xml. Duplicated here
# (not env.ref'd) because pre-migrate runs BEFORE the data file reloads
# — env.ref of the template at this point returns the OLD body.
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
    """Unwrap mail.template.body_html — Odoo 17 stores translated fields
    as a JSONB dict (lang_code -> html). Return a flat list of strings
    to scan for the legacy marker.
    """
    if value is None:
        return []
    if isinstance(value, dict):
        return [v for v in value.values() if v]
    return [value]


def _has_legacy_marker(value):
    """True iff the body contains the literal fallback-paragraph text
    that ships only in v17.0.1.1.0. Substring match handles both the
    hyphen and em-dash variants.
    """
    return any('Booking link unavailable' in s for s in _body_strings(value))


def _refreshed_payload(existing, new_body):
    """Return the value to bind into ``UPDATE mail_template.body_html``.

    ``body_html`` is ``fields.Html(translate=True)`` — column type is
    ``jsonb`` (see odoo/fields.py:2011). Raw SQL writes MUST go through
    ``psycopg2.extras.Json`` so the value is bound as a JSON literal;
    a bare Python str would generate ``UPDATE … SET body_html = 'plain'``
    which Postgres rejects with ``invalid input syntax for type json``.

    Translatable values are stored as ``{lang_code: html_string}``; we
    overwrite every language key the row already has so a candidate who
    sees the email in their language doesn't get an empty body. If the
    row stores a bare string (defensive — should not happen in 17 but
    can in mid-migration states), we fall back to ``{'en_US': new_body}``.
    """
    if isinstance(existing, dict) and existing:
        return Json({lang: new_body for lang in existing.keys()})
    return Json({'en_US': new_body})


def migrate(cr, version):
    # Resolve the canonical record id (may be absent if the user never
    # installed prior versions cleanly — defensive).
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

    cr.execute(
        """
        SELECT id, body_html
          FROM mail_template
         WHERE body_html::text ILIKE %s
        """,
        ('%Booking link unavailable%',),
    )
    rows = cr.fetchall()
    if not rows:
        _logger.info(
            "hr_recruitment_call_stage 17.0.5.0.0: no mail.template "
            "rows contain the legacy 'Booking link unavailable' "
            "marker — nothing to refresh.")
        return

    refreshed_ids = []
    canonical_refreshed = False
    for tmpl_id, body in rows:
        if not _has_legacy_marker(body):
            # ILIKE on jsonb::text could in theory hit a key/escape
            # outside our payload — re-check via the unwrap helper.
            continue
        if tmpl_id == canonical_id:
            # Don't UPDATE directly; clear noupdate so the data-file XML
            # body reloads later in this upgrade. Keeps the canonical
            # row in lock-step with the manifest.
            cr.execute(
                """
                UPDATE ir_model_data
                   SET noupdate = false
                 WHERE module = 'hr_recruitment_call_stage'
                   AND name   = 'mail_template_call_invite_generic'
                """,
            )
            canonical_refreshed = True
            continue
        # Duplicate / detached template — rewrite directly. We do not
        # touch the row's ir_model_data (if any) since we're not
        # claiming ownership of recruiter copies.
        cr.execute(
            "UPDATE mail_template SET body_html = %s WHERE id = %s",
            (_refreshed_payload(body, _SHIPPED_BODY), tmpl_id),
        )
        refreshed_ids.append(tmpl_id)

    if canonical_refreshed:
        _logger.info(
            "hr_recruitment_call_stage 17.0.5.0.0: canonical template "
            "carried the legacy fallback paragraph — cleared noupdate "
            "so the v17.0.5.0.0 XML body reloads in this upgrade.",
        )
    if refreshed_ids:
        _logger.info(
            "hr_recruitment_call_stage 17.0.5.0.0: rewrote body_html "
            "on %d duplicated/detached mail.template row(s) carrying "
            "the legacy fallback paragraph — ids=%s.",
            len(refreshed_ids), refreshed_ids,
        )
