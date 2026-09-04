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