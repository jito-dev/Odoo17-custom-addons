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
| `views/webclient_templates.xml` | Google Fonts injection + theme-color meta tag |

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
