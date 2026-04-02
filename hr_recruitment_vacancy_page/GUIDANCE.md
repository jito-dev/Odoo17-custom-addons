# HR Recruitment Vacancy Page

## What the Module Does

Dynamically builds public vacancy pages from per-job configuration. Adds a "Published Job Configuration" section to Job Positions where users can configure what appears on the public vacancy page, with the option to pull data from Job Context or enter it manually.

## Main Models

- **hr.job** (extended via `_inherit`) — all fields live on the existing Job Position model:
  - Job Context fields (on Recruitment tab):
    - `job_title` (Char) — vacancy title
    - `job_description_context` (Html) — detailed job description with requirements, activities, etc.
    - `salary_min`, `salary_max` (Monetary) — salary range
    - `experience_years_min`, `experience_years_max` (Integer) — experience range (both optional)
  - Feature toggle: `use_published_config`
  - "Take from Job Context" booleans: `title_from_context`, `short_desc_from_context`, `long_desc_from_context`, `salary_from_context`, `experience_from_context`
  - Manual override fields for each configurable field
  - Computed resolved fields: `published_title`, `published_short_desc`, `published_long_desc`, `published_salary_min`, `published_salary_max`, `published_experience_min`, `published_experience_max`, `published_salary_display`, `published_experience_display`

## Views

- **Backend**: `hr_job_views.xml` — extends hr.job form:
  - Adds "Job Context Details" section on Recruitment page (title, description, salary range, experience range)
  - Adds "Published Job Configuration" notebook tab with toggle and per-field context/manual controls
- **Website**: `website_vacancy_templates.xml` — overrides `website_hr_recruitment.detail` and `website_hr_recruitment.index` templates conditionally when `use_published_config` is enabled

## Business Logic

- `published_salary_display` formats salary as: "$X - $Y", "From $X", "Up to $Y", or empty
- `published_experience_display` formats experience as: "X - Y years", "X+ years", "Up to Y years", or empty
- When `use_published_config` is False, the website pages render using standard Odoo behavior
- All "from context" checkboxes default to True — by default data comes from the Job Context fields
- Title "from context" references `job_title`; Long description "from context" references `job_description_context`; Short description "from context" references base `description` field

## Patterns and Constraints

- No new models created — all fields on hr.job
- No new ACL needed — inherits existing hr.job access rules
- No controller changes — existing controller passes full job record to templates
- Website templates use `t-if="job.use_published_config"` for conditional rendering
