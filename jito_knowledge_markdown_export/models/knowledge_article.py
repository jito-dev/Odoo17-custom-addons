import re

import markdown

from odoo import _, api, models
from odoo.exceptions import UserError, ValidationError


class KnowledgeArticle(models.Model):
    _inherit = 'knowledge.article'

    _JITO_MARKDOWN_EXTENSIONS = [
        'fenced_code',
        'tables',
        'nl2br',
        'sane_lists',
    ]
    _JITO_MARKDOWN_MAX_BYTES = 5 * 1024 * 1024  # 5 MB guardrail

    @api.model
    def jito_import_markdown(self, filename=None, content=None, parent_id=None):
        """Create a new article from Markdown text.

        Extracts the title from the first H1 line (``# ...``) in the markdown,
        falling back to the filename (without its extension) if no H1 is found.
        The remainder is converted to HTML and stored on the new article's
        ``body`` field (which is a sanitized HTML field).

        :param str filename: original filename of the uploaded markdown file.
            Used for the fallback title and for the size guard.
        :param str content: UTF-8 markdown text.
        :param int parent_id: id of the article that will become the parent of
            the newly created one. When falsy, the new article is created at
            the root of the user's workspace.
        :return: id of the newly created ``knowledge.article``.
        """
        if not isinstance(content, str):
            raise ValidationError(_("Markdown content must be text."))

        if len(content.encode('utf-8')) > self._JITO_MARKDOWN_MAX_BYTES:
            raise UserError(_(
                "Markdown file is too large (limit: %s MB).",
                self._JITO_MARKDOWN_MAX_BYTES // (1024 * 1024),
            ))

        title, body_md = self._jito_extract_markdown_title(content, filename)
        body_html = markdown.markdown(
            body_md,
            extensions=self._JITO_MARKDOWN_EXTENSIONS,
            output_format='html',
        )

        article = self.article_create(
            title=title,
            parent_id=int(parent_id) if parent_id else False,
        )
        if body_html:
            article.body = body_html
        return article.id

    @staticmethod
    def _jito_extract_markdown_title(content, filename):
        lines = (content or '').splitlines()
        idx = 0
        while idx < len(lines) and not lines[idx].strip():
            idx += 1

        title = None
        if idx < len(lines):
            match = re.match(r'^\s*#\s+(.+?)\s*#*\s*$', lines[idx])
            if match:
                title = match.group(1).strip() or None
                if title:
                    lines = lines[:idx] + lines[idx + 1:]

        if not title:
            base = (filename or '').rsplit('/', 1)[-1]
            base = re.sub(r'\.(md|markdown|mdown|mkdn)$', '', base, flags=re.IGNORECASE)
            title = base.strip() or _("Imported Article")

        return title, '\n'.join(lines).strip()
