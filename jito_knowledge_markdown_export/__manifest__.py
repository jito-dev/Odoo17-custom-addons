{
    'name': 'Jito Knowledge Markdown Import/Export',
    'version': '17.0.1.2.0',
    'category': 'Productivity/Knowledge',
    'summary': 'Import and export Knowledge articles as Markdown (.md) files',
    'description': """
        Adds two buttons to the Knowledge article topbar (3-dots
        "More actions" menu):

        - "Export to Markdown": downloads the current article body as a
          .md file (HTML -> Markdown via the `markdownify` library).
        - "Import from Markdown": opens a file picker and creates a new
          child article under the current one from the selected .md
          file (Markdown -> HTML via the `markdown` library).
    """,
    'author': 'Jito',
    'license': 'LGPL-3',
    'depends': ['knowledge'],
    'data': [],
    'assets': {
        'web.assets_backend': [
            'jito_knowledge_markdown_export/static/src/xml/knowledge_topbar_inherit.xml',
            'jito_knowledge_markdown_export/static/src/js/knowledge_topbar_patch.js',
        ],
    },
    'external_dependencies': {
        'python': ['markdownify', 'markdown'],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
