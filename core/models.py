from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Single Users table for BOTH roles (Citizen and Officer), distinguished
    by the `role` field — NOT separate tables per role.
    """
    ROLE_CHOICES = [
        ('citizen', 'Citizen'),
        ('officer', 'Officer'),
    ]
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='citizen')

    def is_officer(self):
        return self.role == 'officer'

    def is_citizen(self):
        return self.role == 'citizen'


class CitizenProfile(models.Model):
    """Extra profile data used for eligibility matching."""
    CATEGORY_CHOICES = [
        ('general', 'General'),
        ('obc', 'OBC'),
        ('sc', 'SC'),
        ('st', 'ST'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='citizen_profile')
    income = models.DecimalField(max_digits=12, decimal_places=2, help_text="Annual income in INR")
    age = models.PositiveIntegerField()
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES)
    state = models.CharField(max_length=100)

    class Meta:
        indexes = [models.Index(fields=['state'])]

    def __str__(self):
        return f"Profile: {self.user.username}"


class Scheme(models.Model):
    """A government welfare scheme."""
    CATEGORY_CHOICES = [
        ('agriculture', 'Agriculture'),
        ('education', 'Education'),
        ('health', 'Health'),
        ('housing', 'Housing'),
        ('employment', 'Employment'),
        ('women_child', 'Women & Child Welfare'),
    ]
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    state_applicable = models.CharField(max_length=100, default='All India')
    official_reference_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=['category'])]

    def __str__(self):
        return self.name


class EligibilityCriteria(models.Model):
    """Weak entity — has no meaning without its parent Scheme."""
    scheme = models.ForeignKey(Scheme, on_delete=models.CASCADE, related_name='criteria')
    min_income = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    max_income = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    min_age = models.PositiveIntegerField(null=True, blank=True)
    max_age = models.PositiveIntegerField(null=True, blank=True)
    category_required = models.CharField(
        max_length=10, choices=CitizenProfile.CATEGORY_CHOICES, null=True, blank=True
    )

    def __str__(self):
        return f"Criteria for {self.scheme.name}"


class Application(models.Model):
    """A citizen's application to a scheme."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    citizen = models.ForeignKey(User, on_delete=models.CASCADE, related_name='applications')
    scheme = models.ForeignKey(Scheme, on_delete=models.CASCADE, related_name='applications')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_applications')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['citizen', 'scheme'], name='one_application_per_scheme')]
        indexes = [models.Index(fields=['status'])]

    def __str__(self):
        return f"{self.citizen.username} -> {self.scheme.name} ({self.status})"


class Document(models.Model):
    """Supporting proof document uploaded against an Application."""
    DOCUMENT_TYPE_CHOICES = [
        ('income_certificate', 'Income Certificate'),
        ('id_proof', 'ID Proof (Aadhaar/Voter ID)'),
        ('category_certificate', 'Category Certificate (SC/ST/OBC)'),
        ('age_proof', 'Age Proof'),
        ('other', 'Other'),
    ]
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=25, choices=DOCUMENT_TYPE_CHOICES)
    file = models.FileField(upload_to='application_documents/%Y/%m/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_document_type_display()} for Application #{self.application_id}"


class StatusLog(models.Model):
    """Audit trail — one row per status change. Populated by a DB trigger (Day 3), not app code."""
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='status_logs')
    old_status = models.CharField(max_length=10, blank=True, null=True)
    new_status = models.CharField(max_length=10)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    reason = models.TextField(blank=True, default='')
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at']

    def __str__(self):
        return f"{self.application_id}: {self.old_status} -> {self.new_status}"