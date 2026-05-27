# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class CallStageTestCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Stage = cls.env['hr.recruitment.stage']
        cls.Job = cls.env['hr.job']
        cls.Applicant = cls.env['hr.applicant']
        cls.Config = cls.env['hr.job.stage.config']
        cls.AppointmentType = cls.env['appointment.type']
        cls.AppointmentInvite = cls.env['appointment.invite']
        cls.CalendarEvent = cls.env['calendar.event']

        cls.dept = cls.env['hr.department'].create({'name': 'Engineering CS'})
        cls.job_designer = cls.Job.create({
            'name': 'Senior Designer CS',
            'department_id': cls.dept.id,
        })
        cls.job_engineer = cls.Job.create({
            'name': 'Senior Engineer CS',
            'department_id': cls.dept.id,
        })

        cls.appt_hr_call = cls.AppointmentType.create({
            'name': 'HR Call CS',
            'appointment_duration': 0.5,
            'appointment_tz': 'UTC',
        })
        cls.appt_tech_call = cls.AppointmentType.create({
            'name': 'Tech Call CS',
            'appointment_duration': 1.0,
            'appointment_tz': 'UTC',
        })

        cls.stage_call = cls.Stage.create({
            'name': 'Call to schedule CS',
            'sequence': 30,
            'job_ids': [(6, 0, [cls.job_designer.id, cls.job_engineer.id])],
        })

        cls.stage_call_booked = cls.env.ref(
            'hr_recruitment_call_stage.stage_call_booked')

    @classmethod
    def _make_applicant(cls, name, job, stage=None):
        vals = {'name': name, 'partner_name': name, 'job_id': job.id}
        if stage:
            vals['stage_id'] = stage.id
        return cls.Applicant.create(vals)

    @classmethod
    def _get_config(cls, job, stage):
        return cls.Config.search([
            ('job_id', '=', job.id),
            ('stage_id', '=', stage.id),
        ], limit=1)

    @classmethod
    def _find_invite(cls, applicant, appt_type=None):
        """v17.0.2.0.0: helper replacing the dropped BookingInvite search.

        Returns the appointment.invite record bound to the given
        applicant (optionally constrained to a specific appointment
        type).
        """
        domain = [('applicant_id', '=', applicant.id)]
        if appt_type:
            domain.append(('appointment_type_ids', 'in', appt_type.ids))
        return cls.env['appointment.invite'].sudo().search(domain, limit=1)
