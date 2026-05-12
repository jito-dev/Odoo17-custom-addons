"""Migration to v17.0.2.20.0 — fix banner rendering in greeting body.

The v17.0.2.17.0–19.0 templates used a ``<t t-set>...</t>`` /
``<t t-if>...</t>`` / ``<t t-else>...</t>`` block to choose the banner
image source between a custom-uploaded base64 banner and a fallback
``res.company.logo``. Odoo's HTML field stores the body via the
``html`` field type which sanitises through ``html_sanitize``. The
sanitiser strips the self-closing slash from ``<t t-set ... />``,
which left ``<t t-set>`` as an open tag with the rest of the
conditional as its body — the QWeb engine then treated the whole
conditional as t-set's *body content* rather than evaluating
t-value, and the banner ``<td>`` rendered **empty**.

This was effectively a silent bug since v17.0.2.17.0: rendered emails
showed no banner at all (the static body still contained the marker
strings, so prior static tests passed, but the *rendered* output
had no ``<img>`` in the banner band).

v17.0.2.20.0 replaces the ``<t>``-wrapped conditional with a single
``<img>`` element whose ``src`` is computed via ``t-att-src=`` and a
Python ternary expression — no wrapping ``<t>`` tags, no nesting that
HTML sanitisation can mangle. ``<img>`` is a void element, so the
sanitiser preserves its attributes verbatim, and the QWeb evaluator
runs the ternary at render time.

Result: rendered emails now contain the actual banner image (custom
``data:image/*;base64,…`` if uploaded, else ``/web/image/res.company/
<id>/logo`` fallback).

Detection: replaces only when the body still has the v17.0.2.19.0
banner-td signature (``t-set="banner_b64"`` followed by the
``t-if="banner_b64"``/``t-else=""`` pair). Already-fixed bodies are
identified by the absence of the ``<t t-set="banner_b64"`` marker
combined with presence of the v18+ copy text. Admin-customised
bodies are left alone.

Idempotent.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

XMLID = 'hr_birthday_reminders.mail_template_birthday_to_employee'

# Marker that uniquely identifies a v17.0.2.17.0–19.0 default body:
# the broken <t t-set> wrapper that needs the fix applied.
BROKEN_BANNER_MARKER = '<t t-set="banner_b64"'

# Identity marker for v17.0.2.18.0–20.0 default copies (so we can
# distinguish "we shipped a default" from "admin wrote their own").
DEFAULT_COPY_MARKER = 'Wishing you a wonderful Happy Birthday!'

NEW_BODY_HTML = """
<table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f6f7f9;padding:24px 0;margin:0;">
    <tr>
        <td align="center">
            <table cellpadding="0" cellspacing="0" border="0" width="600" style="background:#ffffff;border:1px solid #e6e8ea;border-radius:6px;font-family:Arial,Helvetica,sans-serif;max-width:600px;width:100%;">
                <tr>
                    <td align="center" style="padding:32px 32px 24px;border-bottom:1px solid #eef0f2;">
                        <img alt="Company banner"
                             style="max-height:96px;max-width:100%;display:inline-block;border:0;"
                             t-att-src="('data:image/*;base64,' + env['ir.config_parameter'].sudo().get_param('hr_birthday_reminders.greeting_banner_b64')) if env['ir.config_parameter'].sudo().get_param('hr_birthday_reminders.greeting_banner_b64') else ('/web/image/res.company/%s/logo' % object.company_id.id)"/>
                    </td>
                </tr>
                <tr>
                    <td style="padding:36px 40px 24px;font-size:15px;line-height:1.65;color:#2c3e50;">
                        <p style="margin:0 0 14px;">Hi <strong t-out="object.name"/>,</p>
                        <p style="margin:0 0 14px;">Wishing you a wonderful Happy Birthday!</p>
                        <p style="margin:0 0 14px;">Today is all about you. We hope your day is filled with joy, great surprises, and the company of people you love. May the year ahead be your best one yet, full of inspiration and happiness.</p>
                        <p style="margin:0 0 14px;">Enjoy your special day to the fullest!</p>
                        <p style="margin:28px 0 0;color:#666;">Best regards,<br/>
                            <strong style="color:#2c3e50;">Jito Team</strong></p>
                    </td>
                </tr>
                <tr>
                    <td style="padding:14px 32px;background:#fafbfc;border-top:1px solid #eef0f2;font-size:11px;color:#9aa0a6;border-radius:0 0 6px 6px;">
                        — Sent automatically on your birthday.
                    </td>
                </tr>
            </table>
        </td>
    </tr>
</table>
"""


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    tmpl = env.ref(XMLID, raise_if_not_found=False)
    if not tmpl:
        _logger.warning(
            "v17.0.2.20.0: greeting template %s not found; skipping.",
            XMLID,
        )
        return

    body = tmpl.body_html or ''
    if BROKEN_BANNER_MARKER not in body and DEFAULT_COPY_MARKER in body:
        _logger.info(
            "v17.0.2.20.0: greeting body already has fixed banner; "
            "skipping."
        )
        return
    if BROKEN_BANNER_MARKER not in body:
        _logger.info(
            "v17.0.2.20.0: greeting body looks customized "
            "(no broken-banner marker); preserving as-is."
        )
        return

    tmpl.sudo().write({'body_html': NEW_BODY_HTML})
    _logger.info(
        "v17.0.2.20.0: rewrote banner band using <img t-att-src=…> "
        "to fix HTML-sanitiser-induced <t t-set> mangling."
    )
