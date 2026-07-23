# -*- coding: utf-8 -*-
"""v17.0.24.19.0 — booking_url cache refresh after minting an invite.

Root cause of "call-invite email sent WITHOUT the Book-a-call button" when a
recruiter moves SEVERAL candidates to the Call Stage at once.

`hr.applicant.booking_url` is a non-stored compute with
`@api.depends('job_id', 'stage_id')`. It resolves the applicant's
`appointment.invite` through a SEARCH, which Odoo's dependency graph cannot
track. Moving applicants to the Call Stage invalidates `booking_url`, and Odoo
recomputes it in ONE batch; applicants whose invite is not minted yet get
`False` cached. `_get_or_create_booking_invite` then creates the invite but,
before the fix, left that stale `False` in the cache — so the tracked send
rendered `object.booking_url == False` and dropped the button (only the first
applicant in the batch kept it).

These tests pin that minting an invite refreshes `booking_url`. Remove the
`invalidate_recordset` in `_get_or_create_booking_invite` and both fail.
"""
from odoo.tests import tagged

from .common import CallStageTestCommon


# Shipped-style call-invite body: renders the button only when a booking URL
# resolves (via the injected ctx OR the applicant field).
_BUTTON_BODY = (
    "<p t-if=\"ctx.get('booking_url') or object.booking_url\">"
    "<a t-att-href=\"ctx.get('booking_url') or object.booking_url\">"
    "Book a call</a></p>"
)


@tagged('post_install', '-at_install')
class TestBookingUrlCacheRefresh(CallStageTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = cls.env['mail.template'].create({
            'name': 'Cache-refresh Call Invite CS',
            'model_id': cls.env.ref('hr_recruitment.model_hr_applicant').id,
            'subject': 'Book your call',
            'body_html': _BUTTON_BODY,
        })

    def _enable_call_stage(self, job, appt_type):
        cfg = self._get_config(job, self.stage_call)
        cfg.write({
            'is_call_stage': True,
            'booking_appointment_type_id': appt_type.id,
            'mail_template_id': self.template.id,
        })
        return cfg

    def test_mint_refreshes_stale_booking_url(self):
        """Directly reproduce the stale cache on a single applicant: read
        booking_url once (caches False — no invite yet), then mint the invite.
        booking_url MUST refresh to the real link, not stay the cached False.
        """
        self._enable_call_stage(self.job_designer, self.appt_hr_call)
        applicant = self._make_applicant(
            'Cache Anna CS', self.job_designer, self.stage_call)

        # Poison the cache exactly like the batch recompute does for a
        # not-yet-minted applicant.
        self.assertFalse(
            applicant.booking_url,
            "precondition: no invite yet, so booking_url is False (now cached)")

        applicant._get_or_create_booking_invite(self.appt_hr_call)

        self.assertTrue(
            applicant.booking_url,
            "after minting the invite, booking_url must refresh to the real "
            "/book/ link — before the fix it stayed the stale cached False")
        self.assertIn('/book/', applicant.booking_url)

    def test_batch_move_every_applicant_keeps_its_button(self):
        """Integration mirror of the production incident: move 3 applicants to
        the Call Stage in ONE write, then fire the tracked hook per record (as
        the mail framework does at precommit) and read each booking_url right
        after — the same read order that poisoned the cache in production.
        EVERY applicant must resolve a link, not only the first in the batch.
        """
        self._enable_call_stage(self.job_designer, self.appt_hr_call)
        applicants = self.Applicant.create([
            {'name': 'Batch %d CS' % i,
             'partner_name': 'Batch %d CS' % i,
             'job_id': self.job_designer.id}
            for i in range(3)
        ])

        # One write → one batch recompute of booking_url across all three.
        applicants.write({'stage_id': self.stage_call.id})

        for applicant in applicants:
            # Mints this applicant's invite (and, with the fix, re-invalidates
            # its booking_url).
            applicant._track_template({'stage_id'})
            # Reading here is what the real tracked send does; for the FIRST
            # applicant it batch-caches the others as False. Each subsequent
            # applicant must still come out fresh thanks to the mint-time
            # invalidation.
            self.assertTrue(
                applicant.booking_url,
                "every batched applicant must resolve a booking link, not just "
                "the first — %s came out empty" % applicant.name)
            self.assertIn('/book/', applicant.booking_url)
