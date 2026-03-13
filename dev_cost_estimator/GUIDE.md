# Dev Cost Estimator — Developer Guide

## Purpose

Fetches salary data from Djinni.co and renders interactive bar charts for selected job categories. Used to estimate developer resource costs.

---

## Models

### `cost.estimator.category`
Plain lookup model. `name` (Char). Seeded via `data/category_data.xml` (48 categories). External IDs are used as the Djinni URL slug. No `active` field — visibility controlled via `enabled_category_ids` on the data model.

### `cost.estimator.cache`
Persistent cache with 24-hour TTL per `(category_id, exp)` pair.
- `category_id` → `cost.estimator.category`
- `exp` (Selection) — experience level
- `avg_min`, `avg_max`, `online_count`, `chart_data` (JSON), `cached_at`
- `is_fresh(hours=24)` — TTL check
- SQL constraint: `UNIQUE(category_id, exp)`

### `cost.estimator.data`
Main workspace model (singleton in practice — one record per session).

**Query inputs:**
- `enabled_category_ids` (M2M) — admin-controlled visible categories; defaults to all
- `query_category_ids` (M2M) — user-selected categories to query
- `exp` (Selection) — years of experience filter
- `multiplier` (Selection) — global salary multiplier (x1 to x3)

**Result fields:**
- `multi_charts_json` (Text, stored) — raw JSON array, one entry per category
- `multi_charts_display_json` (Text, computed) — multiplier applied + salary display strings formatted

**Actions (all return `False` for no-reload refresh):**
- `action_find_estimate` — fetches data for selected categories (cache-aware)
- `action_force_refresh` — same but bypasses cache
- `action_clear` — resets inputs and results
- `action_export_pdf` — triggers PDF client action with `multi_charts_display_json`

---

## Data Flow

1. User selects categories in `query_category_ids` and clicks **Find**
2. `_build_multi_charts_json(force=False)` iterates categories, calls `_fetch_for_category` per category
3. `_fetch_for_category` checks `cost.estimator.cache`; on miss or force, calls `_fetch_api_for_slug`
4. `_fetch_api_for_slug` makes HTTP GET to `https://djinni.co/salaries/`, parses HTML response
5. `_extract_chart_data` extracts histogram data, avg range, online count from embedded `<script type="module">`
6. `_parse_histogram_points` normalises raw histogram; `_synthetic_points` generates bell-curve fallback when no data
7. Cache upserted, result stored in `multi_charts_json`
8. `_compute_multi_charts_display_json` applies `multiplier`, formats salary strings → `multi_charts_display_json`
9. `MultiSalaryChartWidget` renders N D3 bar charts vertically

---

## Frontend

### `multi_salary_chart_widget.js`
Owl component bound to `multi_charts_display_json` (type: text). Loads D3 v7 from `/dev_cost_estimator/static/lib/d3/d3.min.js`. Renders one section per category: header (name + salary pills), D3 bar chart, footer (online count + date).

### `pdf_export.js`
Client action `dev_cost_estimator.export_pdf`. Loads D3 + jsPDF + html2canvas. Renders off-screen DOM sections (740px), captures via html2canvas, stitches into A4 PDF.

---

## Patterns & Constraints

- **No-reload:** Actions return `False` → Odoo converts to `ir.actions.act_window_close` → form `onClose` reloads record in place
- **D3:** v7.9.0 UMD bundled at `static/lib/d3/d3.min.js`; loaded via `loadJS`
- **Cache TTL:** 24 hours per `(category_id, exp)` pair
- **Slug resolution:** Uses XML external ID as Djinni URL slug; falls back to normalised category name
- **Synthetic points:** Bell-curve histogram generated when Djinni returns no histogram data
- **Module version:** `17.0.1.24.0`
