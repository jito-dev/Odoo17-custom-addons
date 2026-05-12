"""Migration to v17.0.2.18.0 — Jito-branded greeting copy.

``data/mail_template_data.xml`` is wrapped in ``<data noupdate="1">``,
so subject/body changes in the XML do NOT auto-apply to existing
installs on ``-u``. This migration overwrites the subject and body
only when the existing template still looks like the v17.0.2.17.0
default (detected by the phrase "Today is your special day"). Admin
who customized via the UI keeps their version intact.

Idempotent: re-running detects the v17.0.2.18.0 marker
("Wishing you a wonderful Happy Birthday!") and skips.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

XMLID = 'hr_birthday_reminders.mail_template_birthday_to_employee'

# Distinctive phrase from the v17.0.2.17.0 default body. Present
# pre-migration; absent from the new v17.0.2.18.0 copy.
V217_MARKER = 'Today is your special day'

# Distinctive phrase from the v17.0.2.18.0 body. Present in the new
# copy; absent from prior versions and from typical admin rewrites.
NEW_MARKER = 'Wishing you a wonderful Happy Birthday!'

NEW_SUBJECT = 'Happy Birthday, {{ object.name }}! 🎂'

NEW_BODY_HTML = """
<table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f6f7f9;padding:24px 0;margin:0;">
    <tr>
        <td align="center">
            <table cellpadding="0" cellspacing="0" border="0" width="600" style="background:#ffffff;border:1px solid #e6e8ea;border-radius:6px;font-family:Arial,Helvetica,sans-serif;max-width:600px;width:100%;">
                <tr>
                    <td style="padding:24px 32px 16px;border-bottom:1px solid #eef0f2;">
                        <t t-set="banner_b64" t-value="env['ir.config_parameter'].sudo().get_param('hr_birthday_reminders.greeting_banner_b64')"/>
                        <t t-if="banner_b64">
                            <img t-attf-src="data:image/*;base64,{{ banner_b64 }}" alt="Company banner" style="max-height:64px;max-width:100%;display:block;border:0;"/>
                        </t>
                        <t t-else="">
                            <img t-attf-src="/web/image/res.company/{{ object.company_id.id }}/logo" alt="Company logo" style="max-height:64px;max-width:100%;display:block;border:0;"/>
                        </t>
                    </td>
                </tr>
                <tr>
                    <td style="padding:32px;font-size:15px;line-height:1.6;color:#2c3e50;">
                        <p style="margin:0 0 16px;">Hi <strong t-out="object.name"/>,</p>
                        <p style="margin:0 0 16px;">Wishing you a wonderful Happy Birthday!</p>
                        <p style="margin:0 0 16px;">Today is all about you. We hope your day is filled with joy, great surprises, and the company of people you love. May the year ahead be your best one yet, full of inspiration and happiness.</p>
                        <p style="margin:0 0 16px;">Enjoy your special day to the fullest!</p>
                        <p style="margin:24px 0 0;">Best regards,<br/>
                            <em>Jito Team</em></p>
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
            "v17.0.2.18.0: greeting template %s not found; skipping.",
            XMLID,
        )
        return

    body = tmpl.body_html or ''
    if NEW_MARKER in body:
        _logger.info(
            "v17.0.2.18.0: greeting body already on v17.0.2.18.0 copy; "
            "skipping."
        )
        return
    if V217_MARKER not in body:
        _logger.info(
            "v17.0.2.18.0: greeting body looks customized (no "
            "v17.0.2.17.0 marker); preserving subject and body as-is."
        )
        return

    tmpl.sudo().write({
        'subject': NEW_SUBJECT,
        'body_html': NEW_BODY_HTML,
    })
    _logger.info(
        "v17.0.2.18.0: replaced subject and body with Jito-branded "
        "greeting copy."
    )
