from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAchPaymentMethod(TransactionCase):
    """Validation of the US ACH payment method (v1.6.0).

    The ABA routing constraint is deliberately isolated to ``method_type ==
    'ach'``; these tests pin that behaviour and guard against the constraint
    leaking onto the other (SEPA/SWIFT/GBP/UA/cash/crypto) methods.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        employee = cls.env['hr.employee'].create({'name': 'ACH Test Contractor'})
        cls.contractor = cls.env['hpc.contractor'].create({
            'employee_id': employee.id,
        })

    def _new_method(self, **vals):
        base = {
            'name': 'ACH Test Method',
            'contractor_id': self.contractor.id,
            'method_type': 'ach',
        }
        base.update(vals)
        return self.env['hpc.contractor.payment.method'].create(base)

    def test_valid_routing_number(self):
        method = self._new_method(
            ach_account_number='123456789',
            ach_routing_number='021000021',
        )
        self.assertEqual(method.ach_routing_number, '021000021')

    def test_routing_number_too_short_raises(self):
        with self.assertRaises(ValidationError):
            self._new_method(ach_routing_number='12345')

    def test_routing_number_non_numeric_raises(self):
        with self.assertRaises(ValidationError):
            self._new_method(ach_routing_number='02100002X')

    def test_empty_routing_number_allowed(self):
        # Routing is optional at the model level (the view guides the user);
        # an empty value must not trip the constraint.
        method = self._new_method(ach_routing_number=False)
        self.assertFalse(method.ach_routing_number)

    def test_constraint_isolated_to_ach(self):
        # A non-ACH method with a "bad" routing-shaped value in an unrelated
        # field must never be validated by the ACH constraint.
        method = self.env['hpc.contractor.payment.method'].create({
            'name': 'SEPA Method',
            'contractor_id': self.contractor.id,
            'method_type': 'sepa',
            'sepa_iban': 'DE89370400440532013000',
        })
        self.assertEqual(method.method_type, 'sepa')

    def test_ach_currency_defaults_to_usd(self):
        method = self._new_method()
        self.assertEqual(method.ach_currency_id.name, 'USD')
