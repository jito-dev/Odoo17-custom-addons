# Dev Cost Estimator — Module Guide (v1.16)

## Purpose
Fetches salary estimation data from Djinni.co for one or more job categories and
a shared experience level. Displays salary range, candidate count, and interactive
D3.js bar charts — one chart per category — all on one form without page reloads.

## Models

### `cost.estimator.category`
Lookup list of job categories (e.g. Python, React.js, DevOps).
Seeded via `data/category_data.xml`. External IDs are used as the Djinni URL slug.
No `active` field — categories are never archived; visibility is controlled by
`cost.estimator.data.enabled_category_ids`.

### `cost.estimator.admin.config`
Per-category multiplier configuration.
- `category` (Char) — category display name; matches `cost.estimator.category.name`
- `multiplier` (Selection) — cost multiplier applied to salary figures (x1..x3)
No `enabled` field — visibility is driven by `enabled_category_ids` on the data model.

### `cost.estimator.data`
Workspace record (single record per user session):
- `enabled_category_ids` (stored Many2many) — admin-controlled list of visible categories.
  Initialised with all categories on `default_get`.
- `query_category_ids` (stored Many2many, table `cost_estimator_query_cat_rel`) — categories
  the user has selected for the current query. Domain: `[('id', 'in', enabled_category_ids)]`.
- `exp` (Selection) — shared experience level for all queried categories.
- `multiplier` (Selection) — global fallback multiplier (per-category admin config takes priority
  in multi-chart mode).
- `multi_charts_json` (Text) — stored JSON array; one entry per queried category with raw
  `{category_id, category_name, avg_min, avg_max, online_count, cached_at, points}`.
- `multi_charts_display_json` (Computed Text) — applies per-category admin config multiplier
  to each entry; adds formatted salary display strings. Consumed by `multi_salary_chart` widget.
- Legacy single-category fields (`avg_min`, `avg_max`, `chart_data_json`, etc.) — kept for
  backward compat; only shown when `multi_charts_json` is absent.

**Actions (both return `False` for in-place record reload):**
- `action_find_estimate` — if `query_category_ids` set: fetches/caches each category and
  writes `multi_charts_json`. Otherwise falls back to legacy single-category path.
- `action_force_refresh` — same but bypasses the cache.

**Internal helpers:**
- `_fetch_for_category(cat, exp, force=False)` — per-category fetch with cache lookup/upsert.
- `_fetch_api_for_slug(slug, exp)` — raw Djinni HTTP request and HTML parse.
- `_build_multi_charts_json(force)` — iterates `query_category_ids`, calls `_fetch_for_category`
  for each, serialises result array to `multi_charts_json`.
- `_compute_multi_charts_display_json` — reads admin config multipliers, scales salaries and
  histogram points, formats display strings.

### `cost.estimator.cache`
Persistent per-(category, exp) cache with 24-hour TTL.
`UNIQUE(category_id, exp)` constraint. `is_fresh(hours=24)` checks TTL.

## Frontend Widgets

### `salary_chart` (single-category, legacy)
`static/src/js/salary_chart_widget.js` — Owl component bound to `chart_display_json`.
Loads D3.js v7 locally. Renders one SVG bar chart.

### `multi_salary_chart` (multi-category)
`static/src/js/multi_salary_chart_widget.js` — Owl component bound to `multi_charts_display_json`.
- Parses JSON array; for each entry renders a self-contained section:
  - **Header**: category name + three salary pills (Monthly / Hourly / Daily).
  - **Chart**: D3 bar chart (same colour logic as single widget — in/partial/out range).
  - **Footer**: candidates online count + data-as-of date.
- Sections stacked vertically; horizontal rule separates them.
- Uses `requestAnimationFrame` for D3 render so `clientWidth` is resolved after DOM insertion.

## Views
`views/cost_estimator.xml` — single form:
- **Header**: "Find" button (highlighted) + "Force Refresh" (visible after first result).
- **Two-column group**: `query_category_ids` + `exp` on left; `enabled_category_ids` +
  `multiplier` on right.
- **Multi-chart section** (visible when `multi_charts_json` is set): `multi_salary_chart` widget.
- **Legacy section** (visible only when `multi_charts_json` is absent and single-cat data exists):
  salary range display + `salary_chart` widget + market info.

## No-Reload Pattern
Actions return `False` → Odoo converts to `ir.actions.act_window_close` → form's `onClose`
calls `model.load()` → Owl widgets react to updated field values → charts re-render in place.

## Multiplier Logic (multi-category mode)
Each category in `multi_charts_display_json` uses the multiplier from its own
`cost.estimator.admin.config` record (looked up by `category_name`). If no admin config
exists for a category, multiplier defaults to x1. Multiplied values appear in both the
salary pill displays and the histogram x-axis.

## Patterns & Constraints
- D3.js v7.9.0 (UMD build) bundled locally at `static/lib/d3/d3.min.js`.
- Cache TTL: 24 hours. Fallback to `_synthetic_points` (bell curve) when API returns no histogram.
- Many2many relation table for `query_category_ids`: `cost_estimator_query_cat_rel`.
- Module version: `17.0.1.16.0`.
