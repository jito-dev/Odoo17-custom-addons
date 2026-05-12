"""Migration to v17.0.2.21.0 — fix banner MIME type.

v17.0.2.20.0 embedded the custom banner as
``data:image/*;base64,…``. The asterisk in the MIME type is **not
valid** per RFC 6838 — browsers and email clients either treat it
as an unknown type and refuse to render the image, or fall back to
heuristic sniffing (Chrome) which is unreliable for inline data
URIs. The visible symptom: the banner image showed up as a broken
image / blank space in template previews and in actual emails.

v17.0.2.21.0 detects the image format from the base64 prefix and
embeds it with the proper MIME type:

- PNG  : base64 starts with ``iVBOR`` (decodes to ``\\x89PNG…``)
- JPEG : base64 starts with ``/9j/``  (decodes to ``\\xff\\xd8\\xff``)
- otherwise: default to ``image/png`` (most-common format)

The expression is a triple-nested ternary inside ``t-att-src``; ugly
but inline (no extra helper function or computed field needed) and
robust to the most common upload formats. GIF / WebP fall under the
default-PNG branch — browsers usually handle the mismatch via
content-sniffing for those.

Bonus fix: ``object.company_id.id`` is wrapped in a guard so that the
fallback URL (when no banner is uploaded AND no ``object`` is
provided, e.g. Email Templates Preview without a selected record)
no longer renders ``/web/image/res.company/None/logo``. Falls back
to company id 1.

Idempotent: detects v17.0.2.20.0 broken ``image/*`` marker and
skips when the v21 ``image/png`` / detection logic is already in
place.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

XMLID = 'hr_birthday_reminders.mail_template_birthday_to_employee'

# Marker unique to v17.0.2.20.0 (the broken image/* MIME type).
V220_BROKEN_MIME = "data:image/*;base64"

# Marker unique to v17.0.2.21.0 (the detection-based MIME).
V221_DETECTION = "startswith('iVBOR')"

NEW_BODY_HTML = """
<table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f6f7f9;padding:24px 0;margin:0;">
    <tr>
        <td align="center">
            <table cellpadding="0" cellspacing="0" border="0" width="600" style="background:#ffffff;border:1px solid #e6e8ea;border-radius:6px;font-family:Arial,Helvetica,sans-serif;max-width:600px;width:100%;">
                <tr>
                    <td align="center" style="padding:32px 32px 24px;border-bottom:1px solid #eef0f2;">
                        <img alt="Company banner"
                             style="max-height:96px;max-width:100%;display:inline-block;border:0;"
                             t-att-src="(('data:image/png;base64,' if (env['ir.config_parameter'].sudo().get_param('hr_birthday_reminders.greeting_banner_b64') or '').startswith('iVBOR') else ('data:image/jpeg;base64,' if (env['ir.config_parameter'].sudo().get_param('hr_birthday_reminders.greeting_banner_b64') or '').startswith('/9j/') else 'data:image/png;base64,')) + env['ir.config_parameter'].sudo().get_param('hr_birthday_reminders.greeting_banner_b64')) if env['ir.config_parameter'].sudo().get_param('hr_birthday_reminders.greeting_banner_b64') else ('/web/image/res.company/%s/logo' % (object.company_id.id if object and object.company_id else 1))"/>
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
            "v17.0.2.21.0: greeting template %s not found; skipping.",
            XMLID,
        )
        return

    body = tmpl.body_html or ''
    if V221_DETECTION in body:
        _logger.info(
            "v17.0.2.21.0: greeting body already has MIME-detection "
            "logic; skipping."
        )
        return
    if V220_BROKEN_MIME not in body:
        _logger.info(
            "v17.0.2.21.0: greeting body looks customized "
            "(no broken image/* MIME marker); preserving as-is."
        )
        return

    tmpl.sudo().write({'body_html': NEW_BODY_HTML})
    _logger.info(
        "v17.0.2.21.0: replaced broken image/* MIME with PNG/JPEG "
        "auto-detection in banner."
    )
