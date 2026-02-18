/** @odoo-module **/

/**
 * HR Recruitment Forms - Form Submission Handler
 *
 * This module handles form validation and submission for custom recruitment forms.
 */

document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('hr_recruitment_form');
    if (!form) return;

    // Add custom validation for required form questions
    form.addEventListener('submit', function(e) {
        let isValid = true;
        const formQuestions = form.querySelectorAll('[name^="form_q_"]');

        formQuestions.forEach(function(field) {
            const container = field.closest('.s_website_form_field');
            if (!container) return;

            const isRequired = container.classList.contains('s_website_form_required');
            if (!isRequired) return;

            let hasValue = false;
            const fieldName = field.name;
            const fields = form.querySelectorAll('[name="' + fieldName + '"]');

            // Check based on input type
            const fieldType = field.type;
            if (fieldType === 'radio' || fieldType === 'checkbox') {
                fields.forEach(function(f) {
                    if (f.checked) hasValue = true;
                });
            } else {
                hasValue = field.value && field.value.trim() !== '';
            }

            if (!hasValue) {
                isValid = false;
                container.classList.add('has-error');
                field.classList.add('is-invalid');
            } else {
                container.classList.remove('has-error');
                field.classList.remove('is-invalid');
            }
        });

        if (!isValid) {
            e.preventDefault();
            // Scroll to first error
            const firstError = form.querySelector('.has-error');
            if (firstError) {
                firstError.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        }
    });

    // Real-time validation feedback
    form.querySelectorAll('[name^="form_q_"]').forEach(function(field) {
        field.addEventListener('change', function() {
            const container = this.closest('.s_website_form_field');
            if (container) {
                container.classList.remove('has-error');
                this.classList.remove('is-invalid');
            }
        });
    });
});
