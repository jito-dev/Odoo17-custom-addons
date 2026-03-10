# jito_document_template — Guidance

## What This Module Does

A reusable Odoo 17 module that manages `.docx` Jinja2 templates and generates rendered
documents (DOCX + optional PDF) from them. This is the Phase 1 core engine.

Consuming modules inherit the `document.generator.mixin` and provide context dicts to
populate template variables.

---

## Main Models

### `document.template`
- Stores `.docx` template files (Binary field with `attachment=True`).
- Fields: `name`, `category` (invoice/agreement/nda/other), `template_file`,
  `template_filename`, `description`, `active`, `generated_count`.
- Tracks changes via `mail.thread`.

### `document.generated`
- History record for each generation attempt.
- Fields: `name` (sequence DOC/XXXX), `template_id`, `res_model`, `res_id`,
  `res_name` (computed display name of source), `docx_attachment_id`,
  `pdf_attachment_id`, `state` (generated/error), `error_message`, `generated_by`.
- Download actions return `ir.actions.act_url` for the stored attachments.

### `document.generator.mixin` (AbstractModel)
- Add to any model via `_inherit = ['document.generator.mixin']`.
- Provides `document_generated_ids` (computed One2many via search), `document_generated_count`.
- Override `_build_document_context(self) -> dict` to pass variables to the template.
- `action_generate_document()` opens the wizard pre-populated with `res_model`/`res_id`.

### `document.generate.wizard` (TransientModel)
- User picks a template (optionally filtered by category), chooses whether to generate PDF.
- Calls `_build_document_context()` on the source record if available.
- On success: creates `document.generated` with DOCX (and PDF) attachments, navigates to form.
- On error: creates `document.generated` in `error` state with the error message.

---

## Business Logic

### Rendering Service (`services/docx_renderer.py`)
Pure Python, no Odoo imports:
- `render_docx(template_bytes, context)` — uses `docxtpl.DocxTemplate` to render.
- `is_libreoffice_available()` — `shutil.which('libreoffice')`.
- `convert_to_pdf(docx_bytes)` — calls LibreOffice headless via subprocess.

**Key details:**
- `docxtpl` is imported lazily inside `render_docx()` to avoid import errors if not installed.
- LibreOffice uses `--norestore` to avoid config dir conflicts in concurrent calls.
- Each conversion uses a unique `tempdir` (created with `tempfile.mkdtemp()`).

---

## Security

Two groups (category: Administration):
- `group_document_template_manager` — full CRUD on templates + generated docs; implies user.
- `group_document_template_user` — read-only on templates, R/W/C on generated docs (no delete).

Templates menu is only visible to managers; Generated Documents menu to all users.

---

## Important Patterns & Constraints

1. **Binary + attachment=True**: `template_file` bytes are retrieved with
   `base64.b64decode(template.template_file)`.
2. **Computed One2many**: `document_generated_ids` uses `search()` inside compute —
   no `inverse_name` because source models vary.
3. **res_name compute**: Gracefully handles `res_model=False` or `res_id=0` with try/except.
4. **Wizard navigation**: `action_generate()` returns an `act_window` action (not `True`) so
   the user is navigated to the generated document form.
5. **PDF warning**: Wizard shows an alert if LibreOffice is unavailable and PDF is requested.

---

## Adding Document Generation to Another Module

```python
class MyModel(models.Model):
    _name = 'my.model'
    _inherit = ['my.model', 'document.generator.mixin']

    def _build_document_context(self):
        self.ensure_one()
        return {
            'name': self.name,
            'date': self.date,
            # ... more variables
        }
```

Add a smart button in the form view:
```xml
<button name="action_generate_document" type="object"
        class="oe_stat_button" icon="fa-file-word-o">
    <field name="document_generated_count" widget="statinfo" string="Documents"/>
</button>
```

---

## Python Dependency

`docxtpl>=0.16.0` — listed in `jito_modules/requirements.txt`.

LibreOffice: system-level install (`apt install libreoffice`). PDF generation
gracefully falls back if LibreOffice is not available.
