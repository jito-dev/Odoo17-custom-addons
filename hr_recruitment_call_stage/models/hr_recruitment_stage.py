# -*- coding: utf-8 -*-
"""v17.0.7.2.0 — Etap 9: replace the unreliable per-job o2m on the stage
form with an explicit header action ("Configure Call Stage for This Job")
that opens the single `hr.job.stage.config` row for (current job, stage)
in a focused modal. Solves the "context.default_job_id is sometimes
absent on the kanban-gear stage form" problem by building the child
form's context server-side from a single source of truth.
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

    def action_configure_call_stage_for_job(self):
        """Open the per-(job, stage) call config row in a focused modal.

        Reads job_id from context.default_job_id (set by actions opened
        from a specific vacancy's Applications kanban). Finds or creates
        the matching hr.job.stage.config row, then returns an act_window
        with target='new' so the recruiter edits exactly one row scoped
        to the job they were already working in.
        """
        self.ensure_one()
        job_id = self.env.context.get('default_job_id')
        if not job_id:
            # Defensive — button is hidden in this case; keep a clear
            # error if the action is reached programmatically.
            raise UserError(_(
                "Open this stage from a specific vacancy's Applications "
                "kanban (Recruitment → Vacancies → [job] → Applications) "
                "to configure its call settings."))
        try:
            job_id = int(job_id)
        except (TypeError, ValueError):
            raise UserError(_("Invalid job context — cannot configure "
                              "call settings."))
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
            'name': _('Call Stage Settings — %(job)s · %(stage)s',
                      job=job.display_name, stage=self.name),
            'res_model': 'hr.job.stage.config',
            'view_mode': 'form',
            'res_id': config.id,
            'target': 'new',
            'context': {
                'default_job_id': job_id,
                'default_stage_id': self.id,
            },
        }
