# -*- coding: utf-8 -*-
"""hr.recruitment.stage extensions for the Call Stage flow.

v17.0.24.16.0 — the per-job Call Stage configuration is no longer reached
through a header button on this (global) stage form. That button opened a
SECOND modal on top of the stage dialog (a nested-dialog anti-pattern with two
Save buttons and a duplicated Email Template field).

v17.0.24.18.0 — the Applications kanban stage gear → Edit opens this stage
form, which carries a **"Configure Call Stage"** button (in the shared
<header> anchor from hr_recruitment_job_stage_config) calling
``action_open_call_config_for_job`` below; it opens the per-(job, stage)
``hr.job.stage.config`` dialog for the vacancy in context. Fireflies adds a
sibling "Interview Questions" button into the same header. (A brief
v17.0.24.17.x experiment put this on a kanban gear-dropdown item instead; it
was reverted in favour of the on-form buttons.)
"""
from odoo import _, api, models
from odoo.exceptions import UserError


class HrRecruitmentStage(models.Model):
    _inherit = 'hr.recruitment.stage'

    @staticmethod
    def _capitalize_stage_name(name):
        """Upper-case the first character only, leaving the rest untouched.

        Deliberately not ``str.title()``/``str.capitalize()``: we want
        ``"tech screen"`` -> ``"Tech screen"`` (not ``"Tech Screen"`` and not
        ``"Tech screen"`` with the tail lower-cased), and the companion
        ``"<stage> — Call Booked"`` suffix to keep its intended casing.
        Idempotent and ``None``/empty-safe.
        """
        if not name:
            return name
        return name[:1].upper() + name[1:]

    @api.model_create_multi
    def create(self, vals_list):
        """Capitalize the first letter of every newly-created stage name.

        Applies to all recruitment stages — recruiter-created (kanban / job
        config wizard) and the auto-minted ``Call Booked`` companion alike —
        so stage labels read consistently. The companion stage is created
        through this same path, so its name is normalised here too.
        """
        for vals in vals_list:
            if vals.get('name'):
                vals['name'] = self._capitalize_stage_name(vals['name'])
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _archive_paired_call_booked_on_call_stage_unlink(self):
        """v17.0.7.0.0 — Etap 8: when a Call Stage is deleted (kanban
        gear → Delete Stage), proactively archive every paired Call
        Booked stage attached to its config rows BEFORE the FK CASCADE
        wipes the config rows themselves (which would skip the
        Python-side ondelete on hr.job.stage.config).
        """
        Config = self.env['hr.job.stage.config'].sudo()
        configs = Config.search([
            ('stage_id', 'in', self.ids),
            ('is_call_stage', '=', True),
        ])
        if configs:
            configs._archive_paired_call_booked(
                exclude_config_ids=configs.ids)

    def action_open_call_config_for_job(self):
        """Open the per-(job, stage) call config for the job currently in
        context, find-or-creating the row.

        Bound to the "Configure Call Stage" button on the stage form (stage
        gear → Edit). ``default_job_id`` comes from the kanban action context
        the stage form was opened with; the button is hidden when it is absent,
        so the UserError below is only a programmatic-call safeguard.
        """
        self.ensure_one()
        job_id = self.env.context.get('default_job_id')
        try:
            job_id = int(job_id) if job_id else False
        except (TypeError, ValueError):
            job_id = False
        if not job_id:
            raise UserError(_(
                "Open this stage from a specific vacancy's Applications kanban "
                "(Recruitment → Vacancies → [job] → Applications) to configure "
                "its call and interview settings."))
        Config = self.env['hr.job.stage.config'].sudo()
        config = Config.search([
            ('job_id', '=', job_id),
            ('stage_id', '=', self.id),
        ], limit=1)
        if not config:
            config = Config.create({
                'job_id': job_id,
                'stage_id': self.id,
            })
        job = self.env['hr.job'].browse(job_id)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Stage settings — %(job)s · %(stage)s',
                      job=job.display_name, stage=self.name),
            'res_model': 'hr.job.stage.config',
            # ``views`` (not just ``view_mode``) is required: this dict is passed
            # straight to the JS action service from the kanban gear item, which
            # never runs the action loader that would otherwise populate it — so
            # ``_preprocessAction`` would crash on ``action.views.map`` without it.
            'views': [[False, 'form']],
            'view_mode': 'form',
            'res_id': config.id,
            'target': 'new',
            'context': {
                'default_job_id': job_id,
                'default_stage_id': self.id,
            },
        }
