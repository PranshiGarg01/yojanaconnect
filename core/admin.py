from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, CitizenProfile, Scheme, EligibilityCriteria, Application, StatusLog, Document


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'is_staff')
    fieldsets = UserAdmin.fieldsets + (('Role', {'fields': ('role',)}),)


@admin.register(CitizenProfile)
class CitizenProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'income', 'age', 'category', 'state')


class EligibilityCriteriaInline(admin.TabularInline):
    model = EligibilityCriteria
    extra = 1


@admin.register(Scheme)
class SchemeAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'is_active')
    inlines = [EligibilityCriteriaInline]


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('citizen', 'scheme', 'status', 'submitted_at')


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('application', 'document_type', 'uploaded_at')


@admin.register(StatusLog)
class StatusLogAdmin(admin.ModelAdmin):
    list_display = ('application', 'old_status', 'new_status', 'changed_at')
    def has_add_permission(self, request):
        return False  # only a DB trigger should ever create these, not a human