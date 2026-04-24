# Helpdesk Quick Report

## What It Does

Adds a **Shift+Right-Click** context menu to the entire Odoo backend that lets any
internal user instantly create a Helpdesk ticket. The ticket is auto-populated with
a screenshot, page context, clicked element details, browser metadata, and recent
console errors.

## How To Use

1. Navigate to any page in Odoo.
2. Hold **Shift** and **Right-Click** anywhere.
3. Click **"Report Issue"** in the context menu.
4. Fill in a title (pre-filled from breadcrumb) and optional description.
5. Click **Submit Report** — a screenshot is captured, the ticket is created,
   and a new tab opens with the ticket.

## Configuration

**Settings > Helpdesk Quick Report > Default Helpdesk Team**

If not configured, the system auto-detects: first a team the user belongs to,
then any available team.

## Module Icon

`static/description/icon.png` — used by Odoo in two places automatically:

1. The Apps menu tile for the module.
2. The Settings page tab icon (Settings > Helpdesk Quick Report). Odoo's
   `settings_form_compiler.js` resolves `<app name="jito_helpdesk_quick_report">`
   to `/jito_helpdesk_quick_report/static/description/icon.png` by convention,
   so no explicit `logo` attribute is needed on the `<app>` tag.

## Architecture

### Frontend (static/src/)

- **`js/quick_report_service.js`** — Global OWL service registered on the `services`
  registry. Listens for `Shift+Right-Click` via `contextmenu` event. Captures all
  context (DOM element, breadcrumb, URL, Odoo model/record, browser info, console
  errors). Handles screenshot capture (getDisplayMedia → html2canvas fallback).
  Builds structured HTML description. Calls the backend controller.

- **`js/quick_report_dialog.js`** — OWL dialog component with Title and Description
  fields. Uses Odoo's `Dialog` component.

- **`xml/quick_report_dialog.xml`** — QWeb template for the dialog.

- **`scss/quick_report.scss`** — Styles for the context menu.

### Backend

- **`controllers/main.py`** — JSON controller at
  `/jito_helpdesk_quick_report/create_ticket`. Creates ticket + attachment using
  `sudo()` because regular `base.group_user` members may lack helpdesk.ticket
  create access. Returns `ticket_id` and `ticket_ref`.

- **`models/res_config_settings.py`** — Adds `quick_report_team_id` field to
  general settings, stored via `ir.config_parameter`.

## Auto-Captured Data

| Data              | Source                               |
|-------------------|--------------------------------------|
| Screenshot        | getDisplayMedia API / html2canvas    |
| Page URL          | window.location.href                 |
| Breadcrumb        | DOM .o_breadcrumb elements           |
| Odoo model/record | URL hash (model, id, view_type)      |
| Clicked element   | event.target DOM traversal           |
| Field name/value  | Closest .o_field_widget              |
| Browser info      | navigator.userAgent, screen size     |
| Console errors    | Patched console.error ring buffer    |
| Reporter          | env.services.user (set as partner)   |

## Security Notes

- The controller uses `auth='user'` — only authenticated internal users can call it.
- `sudo()` is used for ticket/attachment creation because not all internal users
  have helpdesk create access. The reporting user is always set as `partner_id`
  for traceability.
