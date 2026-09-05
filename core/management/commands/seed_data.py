from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import User, CitizenProfile, Scheme, EligibilityCriteria


class Command(BaseCommand):
    help = "Seeds demo users and real scheme data."

    @transaction.atomic
    def handle(self, *args, **kwargs):
        officer, created = User.objects.get_or_create(
            username='officer1', defaults={'email': 'officer1@yojanaconnect.gov.in', 'role': 'officer'}
        )
        if created:
            officer.set_password('officer@123')
            officer.role = 'officer'
            officer.save()
            self.stdout.write(self.style.SUCCESS('Created officer1 / officer@123'))

        citizen1, created = User.objects.get_or_create(
            username='citizen1', defaults={'email': 'citizen1@example.com', 'role': 'citizen'}
        )
        if created:
            citizen1.set_password('citizen@123')
            citizen1.role = 'citizen'
            citizen1.save()
            CitizenProfile.objects.create(user=citizen1, income=120000, age=17, category='general', state='Tamil Nadu')
            self.stdout.write(self.style.SUCCESS('Created citizen1 / citizen@123 (low income, age 17)'))

        citizen2, created = User.objects.get_or_create(
            username='citizen2', defaults={'email': 'citizen2@example.com', 'role': 'citizen'}
        )
        if created:
            citizen2.set_password('citizen@123')
            citizen2.role = 'citizen'
            citizen2.save()
            CitizenProfile.objects.create(user=citizen2, income=900000, age=45, category='general', state='Karnataka')
            self.stdout.write(self.style.SUCCESS('Created citizen2 / citizen@123 (high income, age 45)'))

        # Real schemes with figures checked against official sources (see README)
        schemes_data = [
            {'name': 'National Means-cum-Merit Scholarship', 'description': 'Scholarship for meritorious students from economically weaker sections, Class 9-12.', 'category': 'education', 'state_applicable': 'All India', 'official_reference_url': 'https://dsel.education.gov.in/scheme/nmmss', 'criteria': {'max_income': 350000, 'min_age': 13, 'max_age': 18}},
            {'name': 'Pradhan Mantri Awas Yojana - Urban 2.0 (EWS)', 'description': 'Interest subsidy on home loans for Economically Weaker Section households.', 'category': 'housing', 'state_applicable': 'All India', 'official_reference_url': 'https://pmay-urban.gov.in/faq', 'criteria': {'max_income': 300000}},
            {'name': 'Ayushman Bharat PM-JAY (Senior Citizen 70+)', 'description': 'Free health insurance for citizens aged 70+, regardless of income.', 'category': 'health', 'state_applicable': 'All India', 'official_reference_url': 'https://pmjay.gov.in/', 'criteria': {'min_age': 70}},
            {'name': 'Indira Gandhi National Old Age Pension Scheme', 'description': 'Monthly pension for BPL senior citizens aged 60+.', 'category': 'employment', 'state_applicable': 'All India', 'official_reference_url': 'https://nsap.nic.in/', 'criteria': {'min_age': 60}},
            {'name': 'Post-Matric Scholarship for SC Students', 'description': 'Tuition and maintenance support for SC students, Class 11 onwards.', 'category': 'education', 'state_applicable': 'All India', 'official_reference_url': 'https://scholarships.gov.in/', 'criteria': {'max_income': 250000, 'min_age': 16, 'max_age': 30, 'category_required': 'sc'}},
        ]

        for data in schemes_data:
            criteria = data.pop('criteria')
            scheme, created = Scheme.objects.get_or_create(name=data['name'], defaults=data)
            if created:
                EligibilityCriteria.objects.create(scheme=scheme, **criteria)
                self.stdout.write(self.style.SUCCESS(f'Created scheme: {scheme.name}'))

        self.stdout.write(self.style.SUCCESS('\nSeeding complete.'))