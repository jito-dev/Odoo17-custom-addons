# Jito Theme Module

## Overview

`jito_theme` is a custom Odoo 17 **backend theme** that applies the
fightflow-hub brand identity to the Odoo Enterprise backend UI.

It does **not** modify the public website (frontend) – it targets only the
authenticated back-office interface.

---

## What It Does

| Feature | Details |
|---|---|
| **Brand color** | Blue-indigo `#2644D9` (derived from `hsl(230, 70%, 50%)`) |
| **Body font** | DM Sans (loaded from Google Fonts) |
| **Heading font** | Space Grotesk (loaded from Google Fonts) |
| **Success** | `#21C45D` – green |
| **Warning** | `#F59F0A` – amber |
| **Danger** | `#DC2828` – red |
| **Dark mode** | Fully supported via separate `.dark.scss` overrides |
| **Table styling** | All list/tree views styled to match fightflow-hub table design |
| **Contacts avatar** | Contacts list shows circular avatar next to each contact name |

Colors are derived from `fightflow-hub-main/src/index.css` CSS variables.

---

## Architecture

### Dependency Chain

```
jito_theme → web_enterprise → web
```

### SCSS Injection Order

Odoo compiles SCSS in this asset bundle order:

```
web._assets_primary_variables
  1. jito_theme/static/src/scss/primary_variables.scss   ← INJECTED FIRST (our overrides, no !default)
  2. web_enterprise/static/src/scss/primary_variables.scss  (uses !default → ours win)
  3. web/static/src/scss/primary_variables.scss             (uses !default → ours win)
```

Because SCSS `!default` only sets a variable if it is **not yet defined**,
injecting our file first (without `!default`) ensures our colors are used
throughout the entire backend.

The same pattern applies to dark mode via `web.dark_mode_variables`.

### Google Fonts

Fonts are injected via QWeb template inheritance on `web.webclient_bootstrap`,
adding `<link>` preconnect + stylesheet tags inside the `<head>`.

---

## Key Files

| File | Purpose |
|---|---|
| `__manifest__.py` | Module descriptor, asset bundle injections |
| `static/src/scss/primary_variables.scss` | Light mode SCSS variable overrides |
| `static/src/scss/primary_variables.dark.scss` | Dark mode SCSS variable overrides |
| `static/src/scss/backend.scss` | Fightflow table styles + contact avatar CSS |
| `static/src/js/contact_avatar_field.js` | OWL widget `jito_contact_name` – avatar+name cell |
| `static/src/xml/contact_avatar_field.xml` | OWL template for the avatar+name widget |
| `views/webclient_templates.xml` | Google Fonts injection + theme-color meta tag |
| `views/res_partner_views.xml` | Inherits res.partner tree view to use `jito_contact_name` |

---

## Contacts Avatar Widget

### How It Works

The `jito_contact_name` OWL field widget wraps the `display_name` (char) field and renders:

```
[ ● avatar image ]  Contact Name
```

The avatar is loaded from `/web/image/res.partner/{id}/avatar_128` — Odoo's
built-in endpoint that returns:
- The contact's uploaded photo (resized to 128 × 128 px) if one exists
- An auto-generated SVG with the contact's initials on a colored background if not

For unsaved (new) records where `resId` is null, a CSS-only initials circle
is rendered from the typed name characters.

### SCSS Classes

| Class | Description |
|---|---|
| `.o_jito_contact_cell` | Flex container: avatar + name side by side |
| `.o_jito_avatar` | 28×28 px rounded image |
| `.o_jito_avatar_initials` | Fallback initials circle for new records |
| `.o_jito_contact_name` | Name `<span>` with truncation |

### Fightflow Table Reference

Ported from `fightflow-hub-main/src/pages/Students.tsx`:
- Table wrapper: `border rounded-lg overflow-hidden bg-card`
- Header: `text-xs text-muted-foreground`, no hover, subtle separator
- Rows: `border-b hover:bg-muted/50 transition-colors`
- Avatar: `h-7 w-7 rounded-full bg-secondary flex items-center justify-center`

---

## Important Constraints

- **Never modify `web` or `web_enterprise` source** – all overrides are via
  inheritance and asset injection.
- The SCSS overrides do **not** use `!default`, which is intentional and
  necessary for them to take precedence.
- Google Fonts require internet access at runtime (browser loads them).
  For air-gapped deployments, self-host the fonts and update the `<link>` URLs.
- Dark mode variables override only brand/primary colors; semantic status
  colors (`$o-success` etc.) in dark mode fall back to web_enterprise's own
  dark defaults which are already well-tested.
