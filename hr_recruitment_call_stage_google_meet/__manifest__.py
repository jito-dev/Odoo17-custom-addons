# -*- coding: utf-8 -*-
{
    'name': 'HR Recruitment Call Stage — Google Meet bridge',
    'version': '17.0.1.8.1',
    'category': 'Human Resources/Recruitment',
    'summary': 'Seamless Call Stage × Google Meet: one stable join link in the '
               'recruiter cockpit, live booking status, and reactive '
               'cancel/reschedule handling.',
    'description': """
HR Recruitment Call Stage — Google Meet bridge
==============================================

A thin bridge between ``hr_recruitment_call_stage`` (recruiter call-stage
workflow) and ``google_meet_integration`` (up-front Meet URL minting). It
surfaces the booked event's Google Meet link in the recruiter cockpit
(``meet_url`` + "Join call" button), keeps the recruiter informed of the
candidate's self-service actions (Calendly-style cancel / reschedule), and
extends ``call_status`` with ``rescheduled`` and ``cancelled`` states.

Neither parent module is modified — all coupling lives here.
""",
    'author': 'Jito',
    'website': 'https://jito.dev',
    'depends': [
        'hr_recruitment_call_stage',
        'google_meet_integration',
        # Provides the native 'google_meet' videocall source: Odoo's Google
        # Calendar sync attaches the Meet conference, the proven mechanism the
        # bridge forces on Call Stage booking types.
        'appointment_google_calendar',
    ],
    'data': [
        'views/hr_applicant_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': True,
    'license': 'LGPL-3',
}
