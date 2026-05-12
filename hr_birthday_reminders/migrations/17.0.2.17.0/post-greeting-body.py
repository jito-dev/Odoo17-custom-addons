"""Migration to v17.0.2.17.0 — Clean Corporate greeting body.

``data/mail_template_data.xml`` is wrapped in ``<data noupdate="1">``,
so upgrading the module **does not** overwrite the existing
``mail_template_birthday_to_employee.body_html`` field. This is by
design — admins can edit templates at runtime via Email Templates
and their changes persist across upgrades.

But the v17.0.2.17.0 redesign is a structural overhaul (single ``<div>``
→ table-based layout with banner band), so we explicitly bring it
forward for upgrades. The migration is **conservative**: it only
touches templates whose body still looks like the v17.0.2.15.0 / v16.0
default. Admin who customized via the UI keeps their version.

Detection logic:

- If the body already contains the v17.0.2.17.0 banner marker
  (``data:image/*;base64``), the migration was already run (or fresh
  install) — skip.
- Else, if the body still has the v17.0.2.15.0 footer phrase
  (``— Sent automatically on your birthday.``) **AND** has no
  ``<table`` (the new layout's signature), assume it is the
  pre-17.0.2.17.0 default and replace it.
- Else (customized: no marker, or wrapped in a table) → leave alone.

Idempotent. Safe to re-run.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

XMLID = 'hr_birthday_reminders.mail_template_birthday_to_employee'

# Detection markers. The v17.0.2.15.0 default body is a single <div>
# with <p> elements. The v17.0.2.17.0 redesign is wrapped in <table>
# blocks. Odoo's HTML editor normalises inline styles on save (adds
# box-sizing, margin shorthands, etc.), so exact-string matching the
# style attribute is fragile. We instead probe for two structural
# signals that survive that normalisation:
#   - the disclaimer text "— Sent automatically on your birthday."
#     is identical in both v17.0.2.15.0 and v17.0.2.17.0 bodies, so
#     it is a reliable "this is one of our defaults" indicator;
#   - the new layout always contains the <table> tag and the
#     `data:image/*;base64` banner marker — the old layout has neither.
V215_DISCLAIMER = "— Sent automatically on your birthday."
NEW_BODY_FLAG = 'data:image/*;base64'

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
                        <p style="margin:0 0 16px;">Dear <strong t-out="object.name"/>,</p>
                        <p style="margin:0 0 16px;">🎉 Today is your special day — the entire <strong t-out="object.company_id.name"/> team wishes you a happy birthday.</p>
                        <p style="margin:0 0 16px;">Wishing you a year filled with joy, success, and growth.</p>
                        <p style="margin:24px 0 0;">Warmest regards,<br/>
                            <em t-out="object.company_id.name"/></p>
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
            "v17.0.2.17.0: greeting template %s not found; "
            "skipping body upgrade.", XMLID,
        )
        return

    current = tmpl.body_html or ''
    if NEW_BODY_FLAG in current:
        _logger.info(
            "v17.0.2.17.0: greeting body already migrated; skipping."
        )
        return
    if '<table' in current or V215_DISCLAIMER not in current:
        # Body is either a table-based layout we don't recognise
        # (admin-customised) or doesn't carry our disclaimer at all
        # (heavily customised). Either way, leave it alone.
        _logger.info(
            "v17.0.2.17.0: greeting body looks customized "
            "(table layout already present or missing our disclaimer); "
            "preserving as-is."
        )
        return

    tmpl.sudo().write({'body_html': NEW_BODY_HTML})
    _logger.info(
        "v17.0.2.17.0: replaced default greeting body with "
        "Clean Corporate layout."
    )
