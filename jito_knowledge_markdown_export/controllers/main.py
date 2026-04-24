import re

from markdownify import MarkdownConverter

from odoo import http
from odoo.http import content_disposition, request


class _TableAwareMarkdownConverter(MarkdownConverter):
    """GFM pipe-table cells can't contain real newlines, so the stock
    `markdownify` collapses any block content (``<ul>``, ``<ol>``, ``<p>``,
    ``<br>``) inside a ``<td>``/``<th>`` onto a single line, losing the
    visual structure. This subclass substitutes those interior newlines with
    literal ``<br>`` tags — inline HTML that every GFM-compatible viewer
    renders as a line break within the cell.
    """

    _INTERIOR_NEWLINES = re.compile(r'[ \t]*\n+[ \t]*')

    def _format_cell(self, el, text):
        colspan = 1
        if 'colspan' in el.attrs and el['colspan'].isdigit():
            colspan = max(1, min(1000, int(el['colspan'])))
        t = self._INTERIOR_NEWLINES.sub('<br>', text.strip())
        return ' ' + t + ' |' * colspan

    def convert_td(self, el, text, parent_tags):
        return self._format_cell(el, text)

    def convert_th(self, el, text, parent_tags):
        return self._format_cell(el, text)

    def convert_br(self, el, text, parent_tags):
        # Keep explicit line breaks inside a cell. Headings (also marked
        # `_inline` upstream) fall through to the stock behavior.
        if 'td' in parent_tags or 'th' in parent_tags:
            return '<br>'
        return super().convert_br(el, text, parent_tags)


def _html_to_markdown(html):
    return _TableAwareMarkdownConverter(
        heading_style='ATX',
        bullets='-',
    ).convert(html or '')


class KnowledgeMarkdownExportController(http.Controller):

    @http.route(
        '/knowledge/article/<int:article_id>/export_markdown',
        type='http',
        auth='user',
        methods=['GET'],
    )
    def export_markdown(self, article_id, **kwargs):
        article = request.env['knowledge.article'].browse(article_id).exists()
        if not article:
            raise request.not_found()

        article.check_access_rights('read')
        article.check_access_rule('read')

        title = (article.name or '').strip() or 'Untitled'
        body_md = _html_to_markdown(article.body).strip()

        content = f'# {title}\n\n{body_md}\n' if body_md else f'# {title}\n'

        safe_name = re.sub(r'[^\w\-. ]', '_', title).strip() or 'article'
        filename = f'{safe_name}.md'

        return request.make_response(
            content.encode('utf-8'),
            headers=[
                ('Content-Type', 'text/markdown; charset=utf-8'),
                ('Content-Disposition', content_disposition(filename)),
            ],
        )
