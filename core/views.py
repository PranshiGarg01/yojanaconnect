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