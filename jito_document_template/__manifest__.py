{
    'name': 'Document Template Engine',
    'version': '17.0.1.14.0',
    'category': 'Administration',
    'summary': 'Jinja2 .docx template engine for document generation',
    'description': """
Document Template Engine
========================
Manages reusable .docx Jinja2 templates and generates documents (docx + PDF) from them.

Features:
- Upload .docx templates with Jinja2 variable placeholders
- Tag templates (with parent/sub-tag hierarchy) for easy filtering
- Test Generator: full-page UI to pick a template, enter JSON variables, generate
- Generate rendered .docx from any Odoo record via the mixin
- Optional PDF conversion via LibreOffice headless
- Document generation history with download links
    """,
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': ['mail'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'views/document_template_tag_views.xml',
        'views/document_template_views.xml',
        'views/document_generated_views.xml',
        'views/document_test_generator_views.xml',
        'wizard/document_generate_wizard_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
