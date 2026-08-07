# web_editor_inline_selector_fix

## What the module does

Stops a `SyntaxError` raised deep inside `web_editor`'s style-inlining from
blocking the user when sending a message from an HTML field (chatter composer,
Knowledge, any `html` field with `sanitize_style`/inline conversion).

Symptom reported by users:

```
Uncaught Promise > Failed to execute 'querySelectorAll' on 'Element':
'"][style$="position: absolute;"]' is not a valid selector.
    at classToStyle → toInline → HtmlField._toInline
```

## Root cause (Odoo 17 core)

`web_editor/static/src/js/backend/convert_inline.js`:

- `getCSSRules(doc)` (line ~1052) iterates **all** `doc.styleSheets`, not only
  Odoo's assets. A browser ad-blocker (Opera's built-in one, uBlock, …) injects
  its cosmetic rules as a `<style>` in the page, so they are read too.
- Each `selectorText` is split with
  `RE_COMMAS_OUTSIDE_PARENTHESES = /,(?![^(]*?\))/g` (line 10). The regex
  protects commas inside parentheses but **not** commas inside quotes.
- A cosmetic rule like
  `div[style*="background-image: url(data:image/gif;base64,"][style$="position: absolute;"]`
  is split in the middle of a quoted value → two invalid selectors.
- `classToStyle()` calls `editable.querySelectorAll(rule.selector)` (line ~408)
  → `SyntaxError` → the `_toInline` promise rejects → sending is blocked.

The bug is upstream, and `odoo17_enterprise/` must not be modified, hence the
client-side patch.

## How the fix works

`static/src/js/html_field_inline_selector_fix.js` patches
`HtmlField.prototype._toInline`:

1. Before calling `super`, if `wysiwyg._rulesCache` is empty, it calls the
   exported `getCSSRules(editable.ownerDocument)` itself.
2. It filters out selectors that `querySelector()` refuses (tested against a
   detached `<div>`; selectors without any quote are skipped as a cheap
   pre-filter, since they cannot be a fragment of a torn quoted selector).
3. It stores the result in `wysiwyg._rulesCache`. `toInline()` uses that cache
   (`convert_inline.js:689-695`) and therefore never recomputes - nor applies -
   the broken selectors.
4. Everything runs in a `try/catch`: this safety net must never itself be the
   reason a message cannot be sent.

Only fragments that are *already* syntactically invalid are dropped, so no Odoo
rule is lost — valid CSS is valid by definition.

## Constraints / upgrade checklist

The patch depends on three core details. Re-check them on every Odoo upgrade:

- `getCSSRules` is still exported from `@web_editor/js/backend/convert_inline`.
- `toInline()` still reads `wysiwyg._rulesCache` before computing rules.
- `HtmlField.prototype._toInline` still exists and still calls `toInline()`.

If upstream fixes the comma splitting (check `RE_COMMAS_OUTSIDE_PARENTHESES`),
this module can simply be uninstalled.

## Known gap

`mass_mailing` does **not** go through `_toInline`: `MassMailingHtmlField.commitChanges`
calls `toInline()` directly on a clone inside a sandboxed `srcdoc` iframe
(`mass_mailing_html_field.js:146`). That path is not covered. No incident has
been reported there — the sandboxed iframe usually does not receive the
ad-blocker's stylesheets. If it ever fails the same way, patch
`MassMailingHtmlField.prototype.commitChanges` to seed `this.wysiwyg._rulesCache`
the same way before calling super (note that `mass_mailing_snippets.js:241`
resets that cache, so the seeding has to happen right before the call).

## Files

- `__manifest__.py` — frontend-only module, depends on `web_editor`.
- `static/src/js/html_field_inline_selector_fix.js` — the patch.
