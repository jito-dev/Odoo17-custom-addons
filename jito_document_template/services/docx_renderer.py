"""
Pure-Python document rendering service.
No Odoo imports — safe to call from tests or outside ORM context.
"""
import io
import os
import re
import shutil
import subprocess
import tempfile


def render_docx(template_bytes: bytes, context: dict) -> bytes:
    """
    Render a .docx Jinja2 template with the given context.

    :param template_bytes: raw bytes of the .docx template file
    :param context: dict of variables to pass to the template
    :returns: rendered .docx as bytes
    :raises: RuntimeError on rendering failure
    """
    # Defer import so module loads cleanly if docxtpl is not yet installed
    from docxtpl import DocxTemplate  # noqa: PLC0415

    with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as tmp_in:
        tmp_in.write(template_bytes)
        tmp_in_path = tmp_in.name

    try:
        tpl = DocxTemplate(tmp_in_path)
        tpl.render(context)
        out_buf = io.BytesIO()
        tpl.save(out_buf)
        return out_buf.getvalue()
    finally:
        os.unlink(tmp_in_path)


def _resolve_ast_node(node):
    """Recursively build a full 'a.b.c' path string from a Jinja2 AST node."""
    import jinja2.nodes  # noqa: PLC0415
    if isinstance(node, jinja2.nodes.Name):
        return node.name
    if isinstance(node, jinja2.nodes.Getattr):
        parent = _resolve_ast_node(node.node)
        return '%s.%s' % (parent, node.attr) if parent else None
    if isinstance(node, jinja2.nodes.Getitem):
        parent = _resolve_ast_node(node.node)
        if parent and isinstance(node.arg, jinja2.nodes.Const):
            return '%s[%r]' % (parent, node.arg.value)
    return None


def _collect_paths_from_source(jinja2_source):
    """Parse a Jinja2 source string and return all full variable-access paths."""
    import jinja2  # noqa: PLC0415
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined)
    paths = set()
    try:
        ast = env.parse(jinja2_source)
        for node in ast.find_all((jinja2.nodes.Name, jinja2.nodes.Getattr, jinja2.nodes.Getitem)):
            path = _resolve_ast_node(node)
            if path:
                paths.add(path)
    except Exception:
        pass
    return paths


def _get_leaf_paths(paths):
    """Keep only paths that are not a strict prefix of any longer path.

    E.g. given {'ctx', 'ctx.name', 'ctx.address.street'},
    returns {'ctx.name', 'ctx.address.street'}.
    """
    result = set()
    for p in paths:
        if not any(other.startswith(p + '.') or other.startswith(p + '[') for other in paths if other != p):
            result.add(p)
    return result


_JINJA2_BUILTINS = frozenset({
    'loop', 'super', 'caller', 'varargs', 'kwargs',
    'true', 'false', 'none', 'True', 'False', 'None',
    'range', 'lipsum', 'dict', 'class', 'joiner', 'cycler',
})

HEADER_URI = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/header'
FOOTER_URI = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer'


def extract_jinja_variables_from_string(text: str) -> list:
    """
    Return a sorted list of leaf Jinja2 variable paths found in a plain string
    (e.g. a filename such as ``Report {{ ctx.name }}-{{ date }}.docx``).

    :param text: any string containing ``{{ ... }}`` / ``{% ... %}`` expressions
    :returns: sorted list of full variable path strings (may be empty)
    """
    import re as _re  # noqa: PLC0415
    tokens = _re.findall(r'\{\{(.+?)\}\}|\{%(.+?)%\}', text, _re.DOTALL)
    if not tokens:
        return []
    combined = '\n'.join(
        ('{{ ' + (e[0] or '') + ' }}') if e[0] else ('{% ' + (e[1] or '') + ' %}')
        for e in tokens
    )
    paths = _collect_paths_from_source(combined) - _JINJA2_BUILTINS
    return sorted(_get_leaf_paths(paths))


def extract_jinja_variables(template_bytes: bytes) -> list:
    """
    Return a sorted list of full Jinja2 variable paths (e.g. ``ctx.employee.name``)
    found in a .docx template, including all headers and footers.

    Word splits template expressions across multiple XML runs; this function
    uses docxtpl's ``patch_xml()`` to reassemble them first, then walks the
    Jinja2 AST to collect every attribute-access chain.  Only leaf-level paths
    are returned (intermediate nodes like ``ctx`` or ``ctx.employee`` are
    omitted when a deeper path such as ``ctx.employee.name`` exists).

    :param template_bytes: raw bytes of the .docx template file
    :returns: sorted list of full variable path strings (may be empty)
    """
    from docxtpl import DocxTemplate  # noqa: PLC0415
    from lxml import etree  # noqa: PLC0415

    with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as tmp:
        tmp.write(template_bytes)
        tmp_path = tmp.name

    try:
        tpl = DocxTemplate(tmp_path)
        tpl.init_docx()

        xml_sources = []

        # Body
        xml_sources.append(tpl.patch_xml(tpl.get_xml()))

        # Headers and footers
        for uri in (HEADER_URI, FOOTER_URI):
            for _key, part in tpl.get_headers_footers(uri):
                try:
                    part_xml = tpl.xml_to_string(etree.fromstring(part.blob))
                    xml_sources.append(tpl.patch_xml(part_xml))
                except Exception:
                    pass

        # Extract {{ expr }} and {% stmt %} tokens from every XML source,
        # build a combined Jinja2 snippet and parse it with the AST walker
        all_paths = set()
        for src in xml_sources:
            tokens = re.findall(r'\{\{(.+?)\}\}|\{%(.+?)%\}', src, re.DOTALL)
            combined = '\n'.join(
                ('{{ ' + (e[0] or '') + ' }}') if e[0] else ('{% ' + (e[1] or '') + ' %}')
                for e in tokens
            )
            all_paths |= _collect_paths_from_source(combined)

        # Remove built-ins, then keep only leaf paths
        all_paths -= _JINJA2_BUILTINS
        leaf_paths = _get_leaf_paths(all_paths)
        return sorted(leaf_paths)

    finally:
        os.unlink(tmp_path)


def _parse_path_segments(path: str) -> list:
    """Normalise a Jinja2 variable path into a list of dict-key segments.

    Handles dot notation (``ctx.name``), string-bracket notation
    (``metadata['key']``) and silently drops numeric index brackets
    (``items[0]``) since we cannot meaningfully navigate list elements
    without runtime data.
    """
    normalized = re.sub(r"\['([^']+)'\]", r'.\1', path)
    normalized = re.sub(r'\["([^"]+)"\]', r'.\1', normalized)
    normalized = re.sub(r'\[\d+\]', '', normalized)
    return [s for s in normalized.split('.') if s]


def resolve_jinja_var(path: str, context: dict):
    """Walk *context* along *path*.

    :returns: ``(value, True)`` when the full path exists,
              ``(None, False)`` if any segment is missing.
    """
    current = context
    for seg in _parse_path_segments(path):
        if isinstance(current, dict) and seg in current:
            current = current[seg]
        else:
            return None, False
    return current, True


def build_rendered_vars_html(variables: list, context: dict) -> str:
    """Return a full-width HTML table mapping *variables* to their resolved
    values from *context*.

    Colour coding:
    - Found & non-empty  → black monospace value
    - Found but empty    → muted "—"
    - Not found          → red "not in context"
    """
    if not variables:
        return (
            '<span style="color:#6c757d;font-style:italic;">'
            'No variables detected in template.</span>'
        )
    rows = []
    for var in variables:
        value, found = resolve_jinja_var(var, context)
        if not found:
            cell = '<span style="color:#dc3545;font-size:12px;">not in context</span>'
        elif value in (None, '', False):
            cell = '<span style="color:#adb5bd;font-style:italic;font-size:12px;">—</span>'
        else:
            safe = str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            cell = '<span style="font-family:monospace;font-size:12px;">%s</span>' % safe
        rows.append(
            '<tr>'
            '<td style="font-family:monospace;font-size:12px;white-space:nowrap;'
            'padding:3px 8px;vertical-align:top;width:45%%;">%s</td>'
            '<td style="font-size:12px;padding:3px 8px;">%s</td>'
            '</tr>' % (var, cell)
        )
    return (
        '<table class="table table-sm table-bordered mb-1" style="width:100%%;">'
        '<thead><tr style="background:#f8f9fa;">'
        '<th style="font-size:12px;padding:3px 8px;">Variable</th>'
        '<th style="font-size:12px;padding:3px 8px;">Rendered Value</th>'
        '</tr></thead>'
        '<tbody>%s</tbody>'
        '</table>'
    ) % ''.join(rows)


def render_string(template_str: str, context: dict) -> str:
    """Render a plain Jinja2 string template with the given context.

    Uses ChainableUndefined so missing variables silently become empty strings
    rather than raising an error.

    :param template_str: a string containing ``{{ ... }}`` Jinja2 expressions
    :param context: variable dict (same structure passed to render_docx)
    :returns: rendered string
    """
    import jinja2  # noqa: PLC0415
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined)
    return env.from_string(template_str).render(context)


def is_libreoffice_available() -> bool:
    """Return True if the 'libreoffice' binary is on the PATH."""
    return shutil.which('libreoffice') is not None


def convert_to_pdf(docx_bytes: bytes) -> bytes:
    """
    Convert a .docx file to PDF using LibreOffice headless.

    :param docx_bytes: raw bytes of the .docx file
    :returns: rendered PDF as bytes
    :raises: RuntimeError if LibreOffice is unavailable or conversion fails
    """
    if not is_libreoffice_available():
        raise RuntimeError('LibreOffice is not installed or not on PATH.')

    tmpdir = tempfile.mkdtemp()
    try:
        docx_path = os.path.join(tmpdir, 'document.docx')
        with open(docx_path, 'wb') as f:
            f.write(docx_bytes)

        result = subprocess.run(
            [
                'libreoffice',
                '--headless',
                '--norestore',
                '--convert-to', 'pdf',
                '--outdir', tmpdir,
                docx_path,
            ],
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode('utf-8', errors='replace')
            raise RuntimeError('LibreOffice conversion failed: %s' % stderr)

        pdf_path = os.path.join(tmpdir, 'document.pdf')
        if not os.path.exists(pdf_path):
            raise RuntimeError('LibreOffice did not produce a PDF file.')

        with open(pdf_path, 'rb') as f:
            return f.read()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
