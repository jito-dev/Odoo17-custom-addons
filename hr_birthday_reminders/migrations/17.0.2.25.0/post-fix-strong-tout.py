"""Migration to v17.0.2.25.0 — fix `<strong t-out/>` self-close corruption.

Same class of bug as v17.0.2.20.0 (`<t t-set/>` self-close): HTML
sanitisation strips the trailing slash from self-closing non-void
elements. When body is later opened in Odoo's WYSIWYG editor (which
admin does via Settings → "Edit greeting template…"), the editor
normalises the malformed structure unpredictably — typically by
wrapping subsequent siblings inside the unclosed tag.

Concrete observed corruption (post-WYSIWYG-edit):

    BEFORE (template XML):
      <p>Hi <strong t-out="object.name"/>,</p>
      <p>Wishing you a wonderful Happy Birthday!</p>
      ...

    AFTER (DB):
      <p>Hi <strong t-out="object.name">,</strong></p>
      <strong t-out="object.name">
          <p>Wishing you a wonderful Happy Birthday!</p>
          <p>Today is all about you...</p>
          <p>Enjoy your special day...</p>
          <p>Best regards, <strong>Jito Team</strong></p>
      </strong>

Rendered output: only "Hi Dmytro Poltavets" survives (the comma
inside first strong is replaced by t-out), then the SECOND strong
also replaces its children with `object.name` — so the 4 paragraphs
disappear. Plain text shows only "Hi Dmytro Poltavets / Dmytro
Poltavets / footer".

Fix: replace the self-close `<strong t-out="object.name"/>` with
the explicit-close variant `<strong t-out="object.name">NAME</strong>`.
The `NAME` placeholder is replaced by QWeb at render-time; the
explicit `</strong>` close prevents future editor-normalisation from
mangling siblings.

This migration:
  1. Detects the corrupted body by searching for the broken
     pattern (outer strong wrapping <p> elements).
  2. Rewrites the body with the safe explicit-close pattern.
  3. Skips clean bodies (already on v25 pattern, or admin-customised
     beyond recognition).
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

XMLID = 'hr_birthday_reminders.mail_template_birthday_to_employee'

# Markers that identify a corrupted v22-v24 body (self-close mangled
# by WYSIWYG editor): outer <strong t-out> tag wraps <p> elements.
CORRUPT_PATTERN_1 = '<strong t-out="object.name"'  # any t-out strong
# v22 default body marker (clean state, self-close still intact).
SELF_CLOSE_MARKER = '<strong t-out="object.name"/>'
# v25 fixed marker.
V25_MARKER = '<strong t-out="object.name">NAME</strong>'
# Phrase that must still be present to confirm this is OUR template.
COPY_MARKER = 'Wishing you a wonderful Happy Birthday!'

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
                        <p style="margin:0 0 14px;">Hi <strong t-out="object.name">NAME</strong>,</p>
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
            "v17.0.2.25.0: template %s not found; skipping.", XMLID,
        )
        return

    body = tmpl.body_html or ''
    if V25_MARKER in body:
        _logger.info(
            "v17.0.2.25.0: greeting body already on v25 explicit-close "
            "pattern; skipping."
        )
        return
    if COPY_MARKER not in body and CORRUPT_PATTERN_1 not in body:
        _logger.info(
            "v17.0.2.25.0: greeting body looks fully customised "
            "(no v22+ markers); preserving as-is."
        )
        return

    tmpl.sudo().write({'body_html': NEW_BODY_HTML})
    _logger.info(
        "v17.0.2.25.0: replaced greeting body with explicit-close "
        "<strong t-out=\"object.name\">NAME</strong> pattern, fixing "
        "WYSIWYG-induced corruption."
    )
