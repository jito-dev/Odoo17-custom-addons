# -*- coding: utf-8 -*-
"""On-hold in stage (v17.0.1.1.0).

Lets a recruiter park a candidate that is "neither good nor bad" in their
CURRENT stage without moving the card — a one-click pause on processing.

Design (see Obsidian "hr_recruitment_job_stage_config - on-hold in stage"):

* A plain ``on_hold`` boolean on ``hr.applicant`` — NOT a stage and NOT a
  reuse of ``kanban_state`` (which already means normal/blocked/done). The
  pair ``on_hold`` + the untouched ``stage_id`` expresses "on hold in stage X".
* One-click: ``action_put_on_hold`` flips the flag and stamps who/when;
  ``on_hold_reason`` / ``on_hold_until`` are edited afterwards on the card.
* Auto-resume: moving the card to a DIFFERENT stage clears the flag — a move
  means the recruiter is processing again, so the flag never goes stale.
* ``on_hold_until`` schedules a single "On-hold review" to-do activity for the
  responsible recruiter; clearing it (or resuming) removes that activity.
"""
from odoo import _, api, fields, models


# Stable marker used to find/refresh the single reminder activity per
# applicant. Deliberately NOT translated so lookups are language-stable.
_ON_HOLD_ACTIVITY_SUMMARY = 'On-hold review'


class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    on_hold = fields.Boolean(
        string='On hold', default=False, copy=False, tracking=True,
        help='Parked in the current stage: kept here without active '
             'processing. Does not move the candidate to another stage.')
    on_hold_reason = fields.Char(
        string='On-hold reason', copy=False,
        help='Optional note on why this candidate is parked.')
    on_hold_date = fields.Datetime(
        string='On hold since', readonly=True, copy=False)
    on_hold_by_id = fields.Many2one(
        'res.users', string='Put on hold by', readonly=True, copy=False)
    on_hold_until = fields.Date(
        string='On hold until', copy=False,
        help='Optional revisit date. When set, a to-do activity is scheduled '
             'for the responsible recruiter on that day.')

    def action_put_on_hold(self):
        for applicant in self:
            if applicant.on_hold:
                continue
            applicant.write({
                'on_hold': True,
                'on_hold_date': fields.Datetime.now(),
                'on_hold_by_id': self.env.user.id,
            })
            applicant.message_post(body=_(
                "Put on hold in stage '%(stage)s'.",
                stage=applicant.stage_id.display_name or _('(no stage)')))
        return True

    def action_resume(self):
        self._on_hold_resume(auto=False)
        return True

    def _on_hold_resume(self, auto=False):
        """Clear the on-hold flag and its metadata. ``auto`` distinguishes the
        stage-move auto-resume from an explicit Resume click (for the chatter
        note). The reminder activity is cleared by the write() hook.
        """
        held = self.filtered('on_hold')
        if not held:
            return
        held.with_context(skip_on_hold_autoresume=True).write({
            'on_hold': False,
            'on_hold_date': False,
            'on_hold_by_id': False,
            'on_hold_until': False,
            'on_hold_reason': False,
        })
        for applicant in held:
            applicant.message_post(body=(
                _("Resumed automatically on stage change.") if auto
                else _("Resumed — back in active processing.")))

    def write(self, vals):
        # Capture who must auto-resume BEFORE the write: records currently on
        # hold whose stage is actually changing. Guard with a context flag so
        # our own resume-write never recurses into this branch.
        autoresume = self.browse()
        if 'stage_id' in vals and not self.env.context.get(
                'skip_on_hold_autoresume'):
            autoresume = self.filtered(
                lambda a: a.on_hold and a.stage_id.id != vals['stage_id'])
        res = super().write(vals)
        if autoresume:
            autoresume._on_hold_resume(auto=True)
        if {'on_hold', 'on_hold_until', 'on_hold_reason'} & set(vals):
            self._on_hold_sync_reminder()
        return res

    def _on_hold_sync_reminder(self):
        """Keep exactly one "On-hold review" to-do activity per applicant in
        sync with ``on_hold`` + ``on_hold_until``: create/update it while a
        revisit date is set, remove it otherwise.
        """
        Activity = self.env['mail.activity'].sudo()
        act_type = self.env.ref(
            'mail.mail_activity_data_todo', raise_if_not_found=False)
        if not act_type:
            return
        for applicant in self:
            existing = Activity.search([
                ('res_model', '=', 'hr.applicant'),
                ('res_id', '=', applicant.id),
                ('summary', '=', _ON_HOLD_ACTIVITY_SUMMARY),
            ])
            if applicant.on_hold and applicant.on_hold_until:
                user = applicant.user_id or self.env.user
                if existing:
                    existing.write({
                        'date_deadline': applicant.on_hold_until,
                        'note': applicant.on_hold_reason or False,
                        'user_id': user.id,
                    })
                else:
                    applicant.activity_schedule(
                        'mail.mail_activity_data_todo',
                        date_deadline=applicant.on_hold_until,
                        summary=_ON_HOLD_ACTIVITY_SUMMARY,
                        note=applicant.on_hold_reason or False,
                        user_id=user.id,
                    )
            elif existing:
                existing.unlink()
