# jito_knowledge_markdown_export

## What this module does

Adds **two** buttons to the Knowledge article topbar's 3-dots
("More actions") dropdown, grouped right after the existing **"Export"**
(PDF) button:

1. **Export to Markdown** — downloads the current article as a `.md`
   file. First line is `# <article.name>` (H1); body HTML
   (`knowledge.article.body`) is converted to real Markdown via
   [`markdownify`](https://pypi.org/project/markdownify/) (headings,
   lists, tables, links, bold/italic, code blocks, images all round-trip).
   Filename is `<sanitized-article-name>.md`.

2. **Import from Markdown** — opens a file picker for `.md`/`.markdown`
   files and creates a **new child article under the current one**. The
   first `# H1` in the file becomes the new article's title (if absent,
   the filename without its extension is used as fallback). The rest is
   converted to HTML via [`markdown`](https://pypi.org/project/Markdown/)
   (extensions: `fenced_code`, `tables`, `nl2br`, `sane_lists`) and
   stored on `knowledge.article.body` (Odoo sanitizes the HTML on write).
   After creation, the UI navigates to the new article.

## Main components

### Python

- `controllers/main.py` → `KnowledgeMarkdownExportController.export_markdown`
  - Route: `GET /knowledge/article/<int:article_id>/export_markdown`
  - Auth: `user`
  - ACL: enforces `read` access on `knowledge.article`.
  - Returns: `text/markdown; charset=utf-8` as an attachment.

- `models/knowledge_article.py` → `KnowledgeArticle.jito_import_markdown`
  - `@api.model` method on the `knowledge.article` model.
  - Call signature: `jito_import_markdown(filename=..., content=..., parent_id=...)`.
  - Extracts title, converts Markdown → HTML, calls `self.article_create(title=..., parent_id=...)`, writes the HTML to `body`, returns the new record id.
  - 5 MB guardrail on the uploaded content.
  - Title fallback order: first H1 line → filename without extension → `"Imported Article"`.
  - Create/read/write ACL is enforced naturally by `article_create` and the ORM.

### Frontend (OWL)

- `static/src/xml/knowledge_topbar_inherit.xml`
  Extends the `knowledge.KnowledgeTopbar` template. Both new buttons are
  inserted after the existing button anchored by
  `t-on-click='this.exportToPdf'`. **"Import from Markdown"** is gated
  on `user_can_write and active` (mirroring the existing "Move To"
  pattern) so it's hidden when the user cannot write to the parent.

- `static/src/js/knowledge_topbar_patch.js`
  Patches `knowledgeTopbar.component.prototype` with:
  - `exportToMarkdown()` — flushes dirty edits (`record.model.root.isDirty()` + `env._saveIfDirty()`) and navigates to the download URL.
  - `importFromMarkdown()` — programmatically creates a hidden `<input type="file">`, reads the selected file with `File.text()`, calls `orm.call("knowledge.article", "jito_import_markdown", [], {filename, content, parent_id})`, then navigates to the returned id via `env.openArticle(newId)`. A success toast is shown via `env.services.notification`.

## External dependencies

- `markdownify` — HTML → Markdown (for export)
- `markdown`    — Markdown → HTML (for import)

Declared in `external_dependencies` and pinned in `requirements.txt`.
Install on the Odoo venv:

```
/home/coder/.venv/odoo17/bin/pip install markdownify markdown
```

## Constraints / known behavior

- **Export scope**: the current article only (children are not concatenated).
- **Import target**: new article is created as a **child of the current
  one**. If no current article id is in context, it becomes a root.
- **Import size**: 5 MB hard limit on the uploaded Markdown payload.
- **HTML sanitization**: both directions end up writing through
  `knowledge.article.body` (which is `fields.Html` with the default
  sanitizer) — `<script>`, inline event handlers, etc. are stripped.
- **Dirty editor**: both actions flush unsaved edits before running so
  they reflect the latest content / navigate cleanly.
- **ACL**: export respects `read`; import respects `create` on
  `knowledge.article` and `write` on the chosen parent.

## Install / test

1. `pip install markdownify markdown` into the Odoo venv.
2. Restart Odoo (or just update the apps list) so the new module is
   detected.
3. Install **"Jito Knowledge Markdown Import/Export"** from *Apps*.
4. Open any Knowledge article → `⋮` menu:
   - **Export to Markdown** → downloads `<title>.md`.
   - **Import from Markdown** → pick a `.md` file → new child article
     appears and opens automatically.
