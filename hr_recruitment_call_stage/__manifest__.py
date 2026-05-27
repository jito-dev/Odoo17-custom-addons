# -*- coding: utf-8 -*-
{
    'name': 'HR Recruitment — Call Stage with Appointments',
    'version': '17.0.7.0.0',
    'category': 'Human Resources/Recruitment',
    'summary': 'Mark a stage as a Call Stage: per-candidate booking link in '
               'the invite email, auto-advance on booking, recruiter-friendly '
               'calendar event names.',
    'description': """
HR Recruitment — Call Stage with Appointments
=============================================

Adds a per-(job, stage) "Call Stage" toggle on ``hr.job.stage.config``.
When ticked, the recruiter picks an ``appointment.type`` and the assigned
email template's "Book a call" button auto-resolves to a candidate-
specific Odoo Appointments URL. On booking confirmation, the applicant
is moved to a companion "Call Booked" stage. Calendar events are renamed
to "{Applicant} — {Appointment Type}" with a smart button back to the
applicant; ICS exports to the candidate use a candidate-friendly
"Interview with {Company} — {Job}" SUMMARY.

See ``GUIDANCE.md`` for the active contracts and
``docs/call_stage_improvement_plan.md`` for the phased roadmap.
""",
    'author': 'Jito',
    'website': 'https://jito.dev',
    'depends': [
        # Foundation: must be the bumped version that reserves the
        # call-stage names in _PAYLOAD_FIELDS (see foundation
        # GUIDANCE v17.0.1.0.13).
        'hr_recruitment_job_stage_config',
        'appointment',
        'calendar',
        # Native bridge: ships `calendar.event.applicant_id` and
        # `appointment.invite.applicant_id` (auto-install when both
        # `appointment` and `hr_recruitment` are present, but we declare
        # the dep explicitly so v17.0.2.0.0 native swap is safe).
        'appointment_hr_recruitment',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/stage_data.xml',
        'data/mail_template_data.xml',
        'views/hr_job_stage_config_views.xml',
        'views/hr_job_stage_create_wizard_views.xml',
        'views/calendar_event_views.xml',
        'views/hr_applicant_views.xml',
        'views/hr_applicant_actions.xml',
        'views/hr_recruitment_stage_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
