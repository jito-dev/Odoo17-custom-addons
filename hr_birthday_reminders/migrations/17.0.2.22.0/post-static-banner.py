"""Migration to v17.0.2.22.0 — ship Jito banner as static asset.

v17.0.2.21.0 made the banner render correctly via data URI (`image/png`
MIME). But the **WYSIWYG editor** in Email Templates form (which the
admin sees when they click "Edit greeting template…") doesn't evaluate
QWeb directives — so `t-att-src` is ignored and the `<img>` has no
real `src` attribute → broken image placeholder.

v17.0.2.22.0 adds a static `src` attribute to the `<img>` element
pointing to the shipped `static/src/img/banner.png` asset. The
WYSIWYG editor now displays the Jito banner directly. At
render-time (in the Preview wizard or by the cron), QWeb evaluates
`t-att-src` and overrides the static `src` — so admin-uploaded
custom banners still take precedence.

Both the **default** (no admin upload) and the **template-editor
preview** use the same static asset URL, giving consistent visual
behaviour from the moment an admin opens the template form.

The fallback URL was simplified: previously
`/web/image/res.company/<id>/logo`, now the same module-static
asset URL. The module is Jito-specific now (signed "Jito Team"), so
"company logo of the deployment's company" no longer makes sense as
a fallback — the Jito banner is the right default.

Idempotent: detects the v17.0.2.22.0 marker `static/src/img/banner.png`
and skips.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

XMLID = 'hr_birthday_reminders.mail_template_birthday_to_employee'

V222_MARKER = '/hr_birthday_reminders/static/src/img/banner.png'

# Any of these markers indicates a pre-v22 default body we can safely
# overwrite. The detection-logic v21 left `startswith('iVBOR')` in
# the template; older versions had other markers.
PRE_V222_MARKERS = (
    "startswith('iVBOR')",  # v21
    "data:image/*;base64",  # v20 (broken MIME)
    '<t t-set="banner_b64"',  # v17–v19 (broken QWeb structure)
)

NEW_BODY_HTML = """
<table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f6f7f9;padding:24px 0;margin:0;">
    <tr>
        <td align="center">
            <table cellpadding="0" cellspacing="0" border="0" width="600" style="background:#ffffff;border:1px solid #e6e8ea;border-radius:6px;font-family:Arial,Helvetica,sans-serif;max-width:600px;width:100%;">
                <tr>
                    <td align="center" style="padding:32px 32px 24px;border-bottom:1px solid #eef0f2;">
                        <img alt="Jito banner"
                             src="/hr_birthday_reminders/static/src/img/banner.png"
                             style="max-height:96px;max-width:100%;display:inline-block;border:0;"
                             t-att-src="(('data:image/png;base64,' if (env['ir.config_parameter'].sudo().get_param('hr_birthday_reminders.greeting_banner_b64') or '').startswith('iVBOR') else ('data:image/jpeg;base64,' if (env['ir.config_parameter'].sudo().get_param('hr_birthday_reminders.greeting_banner_b64') or '').startswith('/9j/') else 'data:image/png;base64,')) + env['ir.config_parameter'].sudo().get_param('hr_birthday_reminders.greeting_banner_b64')) if env['ir.config_parameter'].sudo().get_param('hr_birthday_reminders.greeting_banner_b64') else '/hr_birthday_reminders/static/src/img/banner.png'"/>
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
            "v17.0.2.22.0: greeting template %s not found; skipping.",
            XMLID,
        )
        return

    body = tmpl.body_html or ''
    if V222_MARKER in body:
        _logger.info(
            "v17.0.2.22.0: greeting body already has static-banner src; "
            "skipping."
        )
        return
    if not any(marker in body for marker in PRE_V222_MARKERS):
        _logger.info(
            "v17.0.2.22.0: greeting body looks customized "
            "(no pre-v22 marker); preserving as-is."
        )
        return

    tmpl.sudo().write({'body_html': NEW_BODY_HTML})
    _logger.info(
        "v17.0.2.22.0: rewrote greeting body with static-banner src "
        "for WYSIWYG-editor visibility."
    )
