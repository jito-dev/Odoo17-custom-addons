# -*- coding: utf-8 -*-
"""PR 2.5: _track_template must be safe on empty self.

Previous implementation did ``applicant = self[0]`` unconditionally,
which crashes with IndexError on an empty recordset. Odoo's tracking
machinery can call _track_template with an empty recordset in edge
cases (batched precommit on an unlinked record), so we guard with
``if not self: return res``.
"""
from odoo.tests.common import tagged

from .common import StageConfigTestCommon


@tagged('post_install', '-at_install')
class TestTrackTemplateEmptyRecordset(StageConfigTestCommon):
    def test_empty_recordset_no_crash(self):
        empty = self.env['hr.applicant']
        # Should return whatever super() returns; key thing is no IndexError.
        result = empty._track_template({'stage_id': True})
        self.assertIsInstance(result, dict)
