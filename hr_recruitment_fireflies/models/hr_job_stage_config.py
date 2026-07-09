# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrJobStageConfig(models.Model):
    """Per-(job, stage) default interview questions.

    Declared here (not in hr_recruitment_job_stage_config) because the feature
    belongs to the Fireflies module; the field *names* are reserved in that
    module's ``_PAYLOAD_FIELDS`` tuple so the stage scope-flip cleanup counts
    these questions as payload and never drops a config row that only holds
    them. The ordered ``interview_question_ids`` rows are seeded verbatim into a
    new interview's recruiter questions
    (``hr.applicant.interview.custom_qa_line_ids``).
    """
    _inherit = 'hr.job.stage.config'

    # Current storage: an ordered, inline-editable drag-list (v17.0.1.17.0).
    interview_question_ids = fields.One2many(
        'hr.job.stage.question', 'config_id',
        string="Interview questions",
        help="Default questions for this (job, stage). When a Fireflies "
             "interview is created for a candidate sitting here, these are "
             "copied into the interview so the recruiter only clicks Ask AI. "
             "The recruiter can still add or remove questions on the interview; "
             "changing this list does not touch existing interviews.",
    )

    # Transient paste box: type/paste several questions (one per line) and they
    # split into individual draggable rows on blur (see _onchange_question_bulk_add).
    # Not stored — it only feeds interview_question_ids.
    question_bulk_add = fields.Text(
        string="Paste questions",
        store=False,
        help="Paste several questions here, one per line, then click away — "
             "each line becomes a row in the list below. Duplicates are "
             "skipped.",
    )

    # Legacy Text storage (one question per line). DORMANT since v17.0.1.17.0:
    # the post-migration split its content into interview_question_ids rows and
    # nothing reads it anymore. Kept (hidden, un-dropped) so no data is lost and
    # the change stays reversible; do not resurrect without a migration back.
    interview_question_template = fields.Text(
        string="Default Interview Questions (legacy)",
        help="Deprecated (v17.0.1.17.0): migrated into the Interview questions "
             "list. Retained dormant for safety; no longer used.",
    )

    @api.onchange('question_bulk_add')
    def _onchange_question_bulk_add(self):
        """Split the pasted multi-line text into individual question rows.

        Fires on blur (Text/Char onchange semantics). Each non-empty line
        becomes a new ``hr.job.stage.question`` appended to the list; duplicates
        (case-insensitive, against what is already present) are skipped so
        pasting twice does not double the list. The paste box is cleared after.
        Uses bare ``(0, 0, ...)`` create-commands, which ADD rows without
        removing the existing ones.
        """
        text = (self.question_bulk_add or '').strip()
        if not text:
            return
        existing = {
            (q.name or '').strip().lower()
            for q in self.interview_question_ids if q.name
        }
        seq = max(self.interview_question_ids.mapped('sequence') or [0])
        commands = []
        for raw in text.splitlines():
            q = raw.strip()
            if not q or q.lower() in existing:
                continue
            existing.add(q.lower())
            seq += 10
            commands.append((0, 0, {'name': q, 'sequence': seq}))
        if commands:
            self.interview_question_ids = commands
        self.question_bulk_add = False

    def _fireflies_question_lines(self):
        """Return the per-stage questions as an order-preserving, de-duplicated
        list of non-empty strings. Single accessor for every consumer (interview
        seeding, autopilot); reads the ``interview_question_ids`` rows."""
        self.ensure_one()
        seen = set()
        lines = []
        for question in self.interview_question_ids.sorted(
                key=lambda q: (q.sequence, q.id)):
            q = (question.name or '').strip()
            if not q:
                continue
            key = q.lower()
            if key in seen:
                continue
            seen.add(key)
            lines.append(q)
        return lines
