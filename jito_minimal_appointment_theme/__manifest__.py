# -*- coding: utf-8 -*-
{
    'name': 'Minimalist Appointment Theme',
    'version': '17.0.1.1.0',
    'category': 'Website/Website',
    'summary': 'Light, minimal restyle of the public appointment booking flow '
               '(recruitment Call Stage bookings only). Restyle plus a client-'
               'side "select + Continue" step on time selection — no change to '
               'booking logic, controllers or fields.',
    'description': """
Minimalist Appointment Theme
============================

A purely *visual* theme layered on top of the standard Odoo Appointments
booking pages. It restyles the three booking steps — Date & time, Details
and Booked — into a clean light look: white surfaces, hairline borders and
a single near-black accent, with a breadcrumb step indicator.

Scope & safety
--------------
* **Recruitment only.** Every visual change is gated on the
  ``recruitment_booking`` flag injected by ``hr_recruitment_call_stage``
  (steps 1 & 2) or, on the confirmation page, on a read-only check that the
  booking's appointment type is wired to a Call Stage config. Non-recruitment
  appointment pages render byte-for-byte unchanged.
* **Styles only.** No JavaScript, no controller/route changes, no model or
  field changes. The booking logic, slot availability and form submission are
  exactly the stock Odoo behaviour — this module only adds a scoped CSS class,
  a breadcrumb, and an SCSS stylesheet.

See ``GUIDANCE.md`` for the contracts and the CSS scoping rules.
""",
    'author': 'Jito',
    'website': 'https://jito.dev',
    'depends': [
        # `recruitment_booking` context flag + `hr.job.stage.config` model used
        # to detect recruitment bookings; also guarantees this module's QWeb
        # inherits load after the call-stage overrides.
        'hr_recruitment_call_stage',
    ],
    'data': [
        'views/appointment_theme_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'jito_minimal_appointment_theme/static/src/scss/minimal_theme.scss',
            # Recruitment-only: turns the instant redirect on time-slot click
            # into a "select + Continue" step with a themed summary card.
            'jito_minimal_appointment_theme/static/src/js/minbook_slot_continue.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
