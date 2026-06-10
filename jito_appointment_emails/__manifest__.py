# -*- coding: utf-8 -*-
{
    'name': 'Jito Appointment Emails',
    'version': '17.0.1.0.0',
    'category': 'Services/Appointment',
    'summary': 'Strip meeting links from appointment emails and add '
               'Cancel/Reschedule portal buttons.',
    'description': """
Jito Appointment Emails
=======================

Customises the stock Odoo appointment mail templates:

* Removes the "How to Join" / videocall link block from the booked,
  attendee-invitation and cancelled emails (no meeting link is exposed
  by email).
* Adds explicit **Reschedule** and **Cancel** buttons that point at the
  public appointment portal routes (``/calendar/view/<token>`` and
  ``/calendar/<token>/cancel``), gated so plain calendar events never
  render broken links.

The two booked/invitation templates are re-declared in full (mail.template
``body_html`` cannot be xpath-inherited). See ``GUIDE.md``.
""",
    'author': 'Jito',
    'website': 'https://jito.dev',
    'depends': [
        'appointment',
    ],
    'data': [
        'data/mail_template_data.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
