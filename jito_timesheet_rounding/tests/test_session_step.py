# -*- coding: utf-8 -*-

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestSessionStep(HttpCase):
    """The step the grid patch reads out of the session.

    ``session_info()`` cannot be called from a plain ``TransactionCase``: core's
    implementation reads ``request.session.uid``, which raises
    ``RuntimeError: object is not bound`` without a real request
    (``web/models/ir_http.py``). So this goes through the JSON route the web
    client itself calls.
    """

    def _session_step(self):
        # `params` must be a dict, not None: the JSON dispatcher does
        # `dict(self.jsonrequest.get('params', {}), **args)` and would raise.
        info = self.make_jsonrpc_request('/web/session/get_session_info', {})
        return info.get('timesheet_rounding_step')

    def test_the_step_is_published_in_the_session(self):
        """The grid patch decides whether to re-read a cell from this value."""
        self.env.company.write({
            'timesheet_rounding_enabled': True,
            'timesheet_rounding_step': '15',
        })
        self.authenticate('admin', 'admin')
        self.assertEqual(self._session_step(), 15)

    def test_the_session_reports_zero_when_rounding_is_off(self):
        """A zero step is what makes the patch cost nothing at all."""
        self.env.company.write({'timesheet_rounding_enabled': False})
        self.authenticate('admin', 'admin')
        self.assertEqual(self._session_step(), 0)

    def test_the_key_is_always_present(self):
        """The patch reads it unconditionally; a missing key would be undefined."""
        self.authenticate('admin', 'admin')
        self.assertIn(
            'timesheet_rounding_step',
            self.make_jsonrpc_request('/web/session/get_session_info', {}),
        )
