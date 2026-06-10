# -*- coding: utf-8 -*-
"""Per-vacancy test_task_link URL field and its email-rendering button.

Lives on hr.job; rendered conditionally in mail_template_test_task_invite
via Jinja `t-if`. URL validation rejects non-http(s) values inline at save.
"""
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestTestTaskLink(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Job = cls.env['hr.job']
        cls.Applicant = cls.env['hr.applicant']
        cls.Template = cls.env.ref(
            'hr_recruitment_test_task.mail_template_test_task_invite')

        cls.job_with_link = cls.Job.create({
            'name': 'JSC TT job with link',
            'add_test_task': True,
            'test_task_link': 'https://github.com/jito/test-task-frontend',
        })
        cls.job_no_link = cls.Job.create({
            'name': 'JSC TT job no link',
            'add_test_task': True,
        })

    def test_valid_https_url_accepted(self):
        self.job_no_link.test_task_link = 'https://example.com/task'
        self.assertEqual(self.job_no_link.test_task_link,
                         'https://example.com/task')

    def test_valid_http_url_accepted(self):
        self.job_no_link.test_task_link = 'http://intranet.local/task'
        self.assertEqual(self.job_no_link.test_task_link,
                         'http://intranet.local/task')

    def test_invalid_scheme_rejected(self):
        for bad_url in (
                'ftp://example.com/task',
                'javascript:alert(1)',
                '/relative/path',
                'github.com/org/repo',
        ):
            with self.assertRaises(
                    ValidationError,
                    msg=f"URL '{bad_url}' must be rejected"):
                self.job_no_link.write({'test_task_link': bad_url})

    def test_empty_url_allowed(self):
        self.job_with_link.test_task_link = False
        self.assertFalse(self.job_with_link.test_task_link)

    def test_email_renders_button_when_link_set(self):
        """Mail template renders 'Open Test Task' button + 'Description:' header
        when the applicant's job has a non-empty test_task_link."""
        applicant = self.Applicant.create({
            'partner_name': 'JSC TT applicant linked',
            'job_id': self.job_with_link.id,
        })
        body = self.Template._render_field('body_html', [applicant.id])[applicant.id]
        self.assertIn('Description:', body)
        self.assertIn('Open Test Task', body)
        self.assertIn('https://github.com/jito/test-task-frontend', body)

    def test_email_skips_button_when_link_empty(self):
        """Without a link, the 'Description:' header and 'Open Test Task'
        button must not appear; the submission portal CTA stays."""
        applicant = self.Applicant.create({
            'partner_name': 'JSC TT applicant unlinked',
            'job_id': self.job_no_link.id,
        })
        body = self.Template._render_field('body_html', [applicant.id])[applicant.id]
        self.assertNotIn('Description:', body)
        self.assertNotIn('Open Test Task', body)
        # Submission CTA stays
        self.assertIn('View Task &amp; Submit', body)

    def test_two_jobs_render_independent_links(self):
        """Same global template — each candidate sees their own job's URL."""
        other_job = self.Job.create({
            'name': 'JSC TT other job',
            'add_test_task': True,
            'test_task_link': 'https://github.com/jito/other-task',
        })
        a1 = self.Applicant.create({
            'partner_name': 'A1', 'job_id': self.job_with_link.id})
        a2 = self.Applicant.create({
            'partner_name': 'A2', 'job_id': other_job.id})

        body_a1 = self.Template._render_field('body_html', [a1.id])[a1.id]
        body_a2 = self.Template._render_field('body_html', [a2.id])[a2.id]

        self.assertIn('test-task-frontend', body_a1)
        self.assertNotIn('other-task', body_a1)
        self.assertIn('other-task', body_a2)
        self.assertNotIn('test-task-frontend', body_a2)
