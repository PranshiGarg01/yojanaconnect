"""
Automated test suite for YojanaConnect.
Run with: python manage.py test

These tests run against a temporary test database Django creates and
destroys automatically — completely separate from your real dev database,
so running tests never touches your actual seeded data.
"""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.models import User, CitizenProfile, Scheme, EligibilityCriteria, Application, StatusLog, Document


class BaseSetup(TestCase):
    def setUp(self):
        self.officer = User.objects.create_user(username='officer1', password='pass1234', role='officer')
        self.citizen = User.objects.create_user(username='citizen1', password='pass1234', role='citizen')
        CitizenProfile.objects.create(user=self.citizen, income=120000, age=17, category='general', state='Tamil Nadu')

        self.scheme = Scheme.objects.create(
            name='Test Scholarship', description='A scheme for testing.',
            category='education', state_applicable='All India',
        )
        EligibilityCriteria.objects.create(scheme=self.scheme, max_income=350000, min_age=13, max_age=18)


class RBACTests(BaseSetup):
    def test_citizen_blocked_from_officer_pages(self):
        self.client.login(username='citizen1', password='pass1234')
        response = self.client.get(reverse('application_list'))
        self.assertEqual(response.status_code, 302)

    def test_officer_can_access_officer_pages(self):
        self.client.login(username='officer1', password='pass1234')
        response = self.client.get(reverse('application_list'))
        self.assertEqual(response.status_code, 200)

    def test_single_users_table_has_role_field(self):
        self.assertEqual(User.objects.filter(role='citizen').count(), 1)
        self.assertEqual(User.objects.filter(role='officer').count(), 1)
        self.assertEqual(User._meta.db_table, 'core_user')


class EligibilityStoredProcedureTests(BaseSetup):
    def test_eligible_citizen_sees_positive_result(self):
        self.client.login(username='citizen1', password='pass1234')
        response = self.client.get(reverse('scheme_detail', args=[self.scheme.pk]))
        self.assertContains(response, 'You are eligible')

    def test_ineligible_citizen_sees_specific_gap_reason(self):
        CitizenProfile.objects.filter(user=self.citizen).update(income=900000)
        self.client.login(username='citizen1', password='pass1234')
        response = self.client.get(reverse('scheme_detail', args=[self.scheme.pk]))
        self.assertContains(response, 'exceeds the limit')


class TransactionAndRollbackTests(BaseSetup):
    def test_apply_creates_application_and_trigger_logs_it(self):
        self.client.login(username='citizen1', password='pass1234')
        self.client.post(reverse('apply_to_scheme', args=[self.scheme.pk]))
        application = Application.objects.get(citizen=self.citizen, scheme=self.scheme)
        self.assertEqual(application.status, 'pending')
        self.assertEqual(StatusLog.objects.filter(application=application).count(), 1)

    def test_duplicate_application_is_prevented(self):
        Application.objects.create(citizen=self.citizen, scheme=self.scheme, status='pending')
        self.client.login(username='citizen1', password='pass1234')
        self.client.post(reverse('apply_to_scheme', args=[self.scheme.pk]), follow=True)
        self.assertEqual(Application.objects.filter(citizen=self.citizen, scheme=self.scheme).count(), 1)

    def test_officer_approval_and_rollback_preserve_full_history(self):
        application = Application.objects.create(citizen=self.citizen, scheme=self.scheme, status='pending')
        Document.objects.create(
            application=application, document_type='income_certificate',
            file=SimpleUploadedFile('doc.pdf', b'x', content_type='application/pdf'),
        )
        self.client.login(username='officer1', password='pass1234')

        self.client.post(reverse('review_application', args=[application.pk]),
                          {'action': 'approved', 'reason': 'Verified successfully.'})
        application.refresh_from_db()
        self.assertEqual(application.status, 'approved')

        self.client.post(reverse('review_application', args=[application.pk]),
                          {'action': 'pending', 'reason': 'Reverting — needs re-check.'})
        application.refresh_from_db()
        self.assertEqual(application.status, 'pending')

        logs = StatusLog.objects.filter(application=application).order_by('changed_at', 'id')
        self.assertEqual(logs.count(), 3)
        self.assertEqual(logs.last().reason, 'Reverting — needs re-check.')


class DocumentGateTests(BaseSetup):
    def test_officer_cannot_approve_without_documents(self):
        application = Application.objects.create(citizen=self.citizen, scheme=self.scheme, status='pending')
        self.client.login(username='officer1', password='pass1234')
        self.client.post(reverse('review_application', args=[application.pk]),
                          {'action': 'approved', 'reason': 'Trying anyway.'})
        application.refresh_from_db()
        self.assertEqual(application.status, 'pending')

    def test_officer_can_approve_after_document_uploaded(self):
        application = Application.objects.create(citizen=self.citizen, scheme=self.scheme, status='pending')
        Document.objects.create(
            application=application, document_type='income_certificate',
            file=SimpleUploadedFile('doc.pdf', b'x', content_type='application/pdf'),
        )
        self.client.login(username='officer1', password='pass1234')
        self.client.post(reverse('review_application', args=[application.pk]),
                          {'action': 'approved', 'reason': 'Document verified.'})
        application.refresh_from_db()
        self.assertEqual(application.status, 'approved')


class FormValidationTests(BaseSetup):
    def test_criteria_form_rejects_impossible_income_range(self):
        from core.forms import EligibilityCriteriaForm
        form = EligibilityCriteriaForm(data={'min_income': 500000, 'max_income': 100000})
        self.assertFalse(form.is_valid())

    def test_document_form_rejects_disallowed_file_type(self):
        from core.forms import DocumentUploadForm
        bad_file = SimpleUploadedFile('malware.exe', b'x', content_type='application/octet-stream')
        form = DocumentUploadForm(data={'document_type': 'other'}, files={'file': bad_file})
        self.assertFalse(form.is_valid())