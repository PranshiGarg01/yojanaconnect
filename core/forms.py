from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User, CitizenProfile, Scheme, EligibilityCriteria, Document


class CitizenSignUpForm(UserCreationForm):
    """Registration form — collects profile data in the same step as account creation."""
    email = forms.EmailField(required=True)
    income = forms.DecimalField(min_value=0, label="Annual income (INR)")
    age = forms.IntegerField(min_value=0, max_value=120)
    category = forms.ChoiceField(choices=CitizenProfile.CATEGORY_CHOICES)
    state = forms.CharField(max_length=100)

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']

    def clean_income(self):
        """Custom validation beyond min_value — catches obvious typos."""
        income = self.cleaned_data['income']
        if income > 100_00_00_000:
            raise forms.ValidationError("That income value looks like a typo — please re-check.")
        return income

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = 'citizen'
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
            CitizenProfile.objects.create(
                user=user, income=self.cleaned_data['income'], age=self.cleaned_data['age'],
                category=self.cleaned_data['category'], state=self.cleaned_data['state'],
            )
        return user


class SchemeForm(forms.ModelForm):
    """Used by Officers to create/edit schemes."""
    class Meta:
        model = Scheme
        fields = ['name', 'description', 'category', 'state_applicable', 'official_reference_url', 'is_active']
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}


class EligibilityCriteriaForm(forms.ModelForm):
    class Meta:
        model = EligibilityCriteria
        fields = ['min_income', 'max_income', 'min_age', 'max_age', 'category_required']

    def clean(self):
        """
        Cross-field validation: an officer shouldn't be able to create a
        criteria row that's mathematically impossible to satisfy.
        """
        cleaned_data = super().clean()
        min_income, max_income = cleaned_data.get('min_income'), cleaned_data.get('max_income')
        min_age, max_age = cleaned_data.get('min_age'), cleaned_data.get('max_age')

        if min_income is not None and max_income is not None and min_income > max_income:
            raise forms.ValidationError("Minimum income cannot be greater than maximum income.")
        if min_age is not None and max_age is not None and min_age > max_age:
            raise forms.ValidationError("Minimum age cannot be greater than maximum age.")
        return cleaned_data


class DocumentUploadForm(forms.ModelForm):
    ALLOWED_EXTENSIONS = ['.pdf', '.jpg', '.jpeg', '.png']
    MAX_FILE_SIZE_MB = 5

    class Meta:
        model = Document
        fields = ['document_type', 'file']

    def clean_file(self):
        file = self.cleaned_data['file']
        ext = '.' + file.name.rsplit('.', 1)[-1].lower() if '.' in file.name else ''
        if ext not in self.ALLOWED_EXTENSIONS:
            raise forms.ValidationError(f"Unsupported file type '{ext}'. Allowed: {', '.join(self.ALLOWED_EXTENSIONS)}")
        if file.size > self.MAX_FILE_SIZE_MB * 1024 * 1024:
            raise forms.ValidationError(f"File too large. Maximum allowed is {self.MAX_FILE_SIZE_MB} MB.")
        return file


class ApplicationReviewForm(forms.Form):
    """Officer uses this to approve/reject/reverse — always requires a reason."""
    ACTION_CHOICES = [
        ('approved', 'Approve'),
        ('rejected', 'Reject'),
        ('pending', 'Revert to Pending (rollback)'),
    ]
    action = forms.ChoiceField(choices=ACTION_CHOICES, widget=forms.RadioSelect)
    reason = forms.CharField(widget=forms.Textarea(attrs={'rows': 2}), required=True,
                              help_text="Required — recorded in the audit trail.")

    def clean_reason(self):
        reason = self.cleaned_data['reason'].strip()
        if len(reason) < 5:
            raise forms.ValidationError("Please provide a meaningful reason (at least 5 characters).")
        return reason