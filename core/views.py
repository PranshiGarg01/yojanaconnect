from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView
from django.db import connection, DatabaseError
from django.shortcuts import render, redirect
from django.contrib import messages

from .forms import CitizenSignUpForm


def officer_required(view_func):
    """Role-based page access — a citizen hitting an officer URL gets redirected, not shown officer data."""
    return user_passes_test(lambda u: u.is_authenticated and u.is_officer(), login_url='dashboard')(view_func)


def call_check_eligibility(citizen_id, scheme_id):
    """Calls our PostgreSQL stored procedure (built Day 3) directly via a raw cursor."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT check_eligibility(%s, %s)", [citizen_id, scheme_id])
            return cursor.fetchone()[0]
    except DatabaseError:
        return None


class YojanaLoginView(LoginView):
    template_name = 'core/login.html'


def signup_view(request):
    if request.method == 'POST':
        form = CitizenSignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            messages.success(request, "Welcome to YojanaConnect!")
            return redirect('dashboard')
    else:
        form = CitizenSignUpForm()
    return render(request, 'core/signup.html', {'form': form})


@login_required
def dashboard(request):
    """
    Officers and citizens see completely different dashboards — this is
    role-based PAGE content, not just role-based page ACCESS.
    """
    if request.user.is_officer():
        return render(request, 'core/dashboard_officer.html')
    else:
        # Pull from eligible_schemes_view — a real DB VIEW built on Day 3,
        # not something we compute in Python.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT scheme_id, scheme_name, scheme_category FROM eligible_schemes_view WHERE citizen_user_id = %s",
                [request.user.id]
            )
            eligible = cursor.fetchall()
        return render(request, 'core/dashboard_citizen.html', {'eligible_schemes': eligible})



from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404
from django.db import transaction
from .models import Scheme, Application


def call_explain_eligibility_gap(citizen_id, scheme_id):
    """Calls the second stored procedure. Postgres TEXT[] arrays come back as Python lists."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT explain_eligibility_gap(%s, %s)", [citizen_id, scheme_id])
            return cursor.fetchone()[0] or []
    except DatabaseError:
        return []


@login_required
def scheme_list(request):
    """Search + filter + pagination."""
    schemes = Scheme.objects.filter(is_active=True)
    query = request.GET.get('q', '').strip()
    category = request.GET.get('category', '').strip()

    if query:
        schemes = schemes.filter(name__icontains=query)
    if category:
        schemes = schemes.filter(category=category)

    paginator = Paginator(schemes.order_by('name'), 6)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'core/scheme_list.html', {
        'page_obj': page_obj, 'query': query, 'category': category,
        'categories': Scheme.CATEGORY_CHOICES,
    })


@login_required
def scheme_detail(request, pk):
    scheme = get_object_or_404(Scheme, pk=pk)
    is_eligible = None
    already_applied = False
    gap_reasons = []
    if request.user.is_citizen():
        is_eligible = call_check_eligibility(request.user.id, scheme.id)
        if is_eligible is None:
            messages.warning(request, "Couldn't verify eligibility right now — please try again shortly.")
        elif not is_eligible:
            gap_reasons = call_explain_eligibility_gap(request.user.id, scheme.id)
        already_applied = Application.objects.filter(citizen=request.user, scheme=scheme).exists()
    return render(request, 'core/scheme_detail.html', {
        'scheme': scheme, 'is_eligible': is_eligible, 'already_applied': already_applied,
        'gap_reasons': gap_reasons,
    })


@login_required
def apply_to_scheme(request, pk):
    """TRANSACTION: eligibility re-check + application creation happen atomically."""
    scheme = get_object_or_404(Scheme, pk=pk)
    if not request.user.is_citizen():
        messages.error(request, "Only citizens can apply to schemes.")
        return redirect('dashboard')

    if Application.objects.filter(citizen=request.user, scheme=scheme).exists():
        messages.warning(request, "You've already applied to this scheme.")
        return redirect('scheme_detail', pk=pk)

    with transaction.atomic():
        eligible = call_check_eligibility(request.user.id, scheme.id)
        if eligible is None:
            messages.error(request, "Couldn't verify eligibility due to a system error — please try again.")
            return redirect('scheme_detail', pk=pk)
        if not eligible:
            messages.error(request, "You are not eligible for this scheme based on your profile.")
            return redirect('scheme_detail', pk=pk)
        Application.objects.create(citizen=request.user, scheme=scheme, status='pending')

    messages.success(request, f"Application submitted for {scheme.name}.")
    return redirect('dashboard')

from .forms import SchemeForm, EligibilityCriteriaForm, ApplicationReviewForm
from .models import EligibilityCriteria


@officer_required
def manage_schemes(request):
    if request.method == 'POST':
        form = SchemeForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Scheme created.")
            return redirect('manage_schemes')
    else:
        form = SchemeForm()
    schemes = Scheme.objects.all().order_by('name')
    return render(request, 'core/manage_schemes.html', {'form': form, 'schemes': schemes})


@officer_required
def add_criteria(request, scheme_id):
    scheme = get_object_or_404(Scheme, pk=scheme_id)
    if request.method == 'POST':
        form = EligibilityCriteriaForm(request.POST)
        if form.is_valid():
            criteria = form.save(commit=False)
            criteria.scheme = scheme
            criteria.save()
            messages.success(request, "Criteria added.")
            return redirect('manage_schemes')
    else:
        form = EligibilityCriteriaForm()
    return render(request, 'core/add_criteria.html', {'form': form, 'scheme': scheme})


@officer_required
def application_list(request):
    applications = Application.objects.select_related('citizen', 'scheme').all()
    status_filter = request.GET.get('status', '')
    if status_filter:
        applications = applications.filter(status=status_filter)

    paginator = Paginator(applications.order_by('-submitted_at'), 8)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'core/application_list.html', {
        'page_obj': page_obj, 'status_filter': status_filter,
    })


@officer_required
def review_application(request, pk):
    """
    Approve / Reject / Rollback. We SET LOCAL two Postgres session variables
    before saving, so the AFTER UPDATE trigger (built Day 3) can record WHO
    made the change and WHY. Status update + audit log write happen in one
    transaction — both succeed together, or neither does.
    """
    application = get_object_or_404(Application, pk=pk)

    if request.method == 'POST':
        form = ApplicationReviewForm(request.POST)
        if form.is_valid():
            new_status = form.cleaned_data['action']
            reason = form.cleaned_data['reason']

            # Business rule: an application can't be approved with zero
            # supporting documents. Rejection/rollback is still allowed.
            if new_status == 'approved' and application.documents.count() == 0:
                messages.error(request, "Cannot approve — no supporting documents uploaded yet.")
                return redirect('review_application', pk=pk)

            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL app.current_user_id = %s", [str(request.user.id)])
                    cursor.execute("SET LOCAL app.reason = %s", [reason])
                application.status = new_status
                application.reviewed_by = request.user
                application.save()  # fires the trigger -> StatusLog row

            messages.success(request, f"Application marked as {new_status}.")
            return redirect('application_list')
    else:
        form = ApplicationReviewForm()

    history = application.status_logs.all()
    return render(request, 'core/review_application.html', {
        'application': application, 'form': form, 'history': history,
        'documents': application.documents.all(),
    })