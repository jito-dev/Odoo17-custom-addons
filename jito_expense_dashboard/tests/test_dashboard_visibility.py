from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class DashboardVisibilityTest(TransactionCase):
    """ Which "Expenses" tile the Finance group shows.

    Two dashboards carried that name: the stock one, fed from `hr.expense`, which
    is empty in a company that books its costs as bills and journal entries, and
    this module's, fed from accounting entries. Only the second one should be on
    the list - the first is hidden, not deleted, so it comes back by dropping one
    record from `data/expense_dashboard.xml`.
    """

    def test_the_stock_expenses_dashboard_is_hidden_from_everyone(self):
        """ No `group_ids` means no user matches the dashboard's record rule. """
        stock = self.env.ref('spreadsheet_dashboard_hr_expense.spreadsheet_dashboard_expense')

        self.assertFalse(
            stock.group_ids,
            "the empty stock Expenses dashboard is visible again - a module upgrade "
            "has restored its groups, re-run -u jito_expense_dashboard",
        )

    def test_this_modules_dashboard_stays_visible(self):
        """ The point of hiding the other one: this is the tile people open. """
        ours = self.env.ref('jito_expense_dashboard.dashboard_expense_accounting')

        self.assertTrue(ours.group_ids, "the accounting Expenses dashboard is visible to nobody")
        for group in (self.env.ref('account.group_account_readonly'),
                      self.env.ref('account.group_account_invoice')):
            self.assertIn(group, ours.group_ids, f"{group.name} lost access to the dashboard")

    def test_an_accountant_sees_one_expenses_dashboard(self):
        """ Read as a user, through the record rule, the way the app lists them. """
        accountant = self.env['res.users'].create({
            'name': "Expenses dashboard reader",
            'login': 'expenses.dashboard.reader',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_invoice').id,
            ])],
        })

        visible = self.env['spreadsheet.dashboard'].with_user(accountant).search(
            [('name', 'ilike', 'expense')]
        )

        self.assertEqual(
            visible, self.env.ref('jito_expense_dashboard.dashboard_expense_accounting'),
            "an accountant should see this module's Expenses dashboard and no other",
        )
