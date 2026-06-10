"""Migration to v17.0.2.19.0 — visual polish of the greeting body.

Same `<data noupdate="1">` constraint as before: XML changes don't
auto-apply on `-u`. This migration overwrites `body_html` only when
the existing body still looks like the v17.0.2.18.0 default
(detected by the v18-specific banner-td padding signature). Admins
who edited via UI keep their version.

Visual changes from v17.0.2.18.0:

- Banner centered horizontally (``align="center"`` on the banner td,
  ``display:inline-block`` on the img) and given more vertical room
  (max-height 64px → 96px, top padding 24px → 32px).
- Body line-height 1.6 → 1.65 and paragraph margins 16px → 14px for
  a tighter, more modern feel; body padding widened to 40px
  horizontally.
- Signature: "Best regards," muted to #666, "Jito Team" emphasised
  with ``<strong>`` (was ``<em>``) in the original dark color.

Idempotent: re-running detects the v19 banner-td signature and skips.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

XMLID = 'hr_birthday_reminders.mail_template_birthday_to_employee'

# v17.0.2.18.0 default banner-td signature — unique enough to be a
# reliable "this is our v18 default" indicator.
V218_BANNER_TD = 'padding:24px 32px 16px;border-bottom:1px solid #eef0f2'

# v17.0.2.19.0 banner-td signature — unique to the polished body.
V219_BANNER_TD = 'padding:32px 32px 24px;border-bottom:1px solid #eef0f2'

NEW_BODY_HTML = """
<table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f6f7f9;padding:24px 0;margin:0;">
    <tr>
        <td align="center">
            <table cellpadding="0" cellspacing="0" border="0" width="600" style="background:#ffffff;border:1px solid #e6e8ea;border-radius:6px;font-family:Arial,Helvetica,sans-serif;max-width:600px;width:100%;">
                <tr>
                    <td align="center" style="padding:32px 32px 24px;border-bottom:1px solid #eef0f2;">
                        <t t-set="banner_b64" t-value="env['ir.config_parameter'].sudo().get_param('hr_birthday_reminders.greeting_banner_b64')"/>
                        <t t-if="banner_b64">
                            <img t-attf-src="data:image/*;base64,{{ banner_b64 }}" alt="Company banner" style="max-height:96px;max-width:100%;display:inline-block;border:0;"/>
                        </t>
                        <t t-else="">
                            <img t-attf-src="/web/image/res.company/{{ object.company_id.id }}/logo" alt="Company logo" style="max-height:96px;max-width:100%;display:inline-block;border:0;"/>
                        </t>
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
            "v17.0.2.19.0: greeting template %s not found; skipping.",
            XMLID,
        )
        return

    body = tmpl.body_html or ''
    if V219_BANNER_TD in body:
        _logger.info(
            "v17.0.2.19.0: greeting body already polished; skipping."
        )
        return
    if V218_BANNER_TD not in body:
        _logger.info(
            "v17.0.2.19.0: greeting body looks customized (no "
            "v17.0.2.18.0 banner-td signature); preserving as-is."
        )
        return

    tmpl.sudo().write({'body_html': NEW_BODY_HTML})
    _logger.info(
        "v17.0.2.19.0: applied visual polish to greeting body."
    )
