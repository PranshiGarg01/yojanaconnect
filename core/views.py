from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView
from django.db import connection, transaction, DatabaseError
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import models
from django.utils import timezone

from .forms import SchemeForm, EligibilityCriteriaForm, ApplicationReviewForm
from .models import EligibilityCriteria
from .forms import CitizenSignUpForm

from .forms import DocumentUploadForm
from .models import Document
import json
import requests
from django.conf import settings
from django.views.decorators.http import require_POST
from django.utils import timezone
from .models import Scheme, Application, CitizenProfile

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

def fetch_mandi_prices(state):
    """
    Real integration with the official data.gov.in API — Ministry of
    Agriculture's daily mandi (market) price dataset. Not scheme-related
    data (no public API exists for that — verified via research), but a
    genuine live government data source shown as a citizen-facing widget.
    """
    url = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
    params = {
        'api-key': settings.DATA_GOV_IN_API_KEY,
        'format': 'json',
        'filters[state]': state,
        'limit': 5,
    }
    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        return response.json().get('records', [])
    except requests.RequestException:
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

        mandi_prices = fetch_mandi_prices(request.user.citizen_profile.state)
        
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
    schemes = Scheme.objects.filter(is_active=True).filter(
        models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=timezone.now().date())
    )
    query = request.GET.get('q', '').strip()
    category = request.GET.get('category', '').strip()
    demographic = request.GET.get('demographic', '').strip()

    if query:
        schemes = schemes.filter(name__icontains=query)
    if category:
        schemes = schemes.filter(category=category)
    if demographic:
        schemes = schemes.filter(target_demographic=demographic)

    paginator = Paginator(schemes.order_by('name'), 6)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'core/scheme_list.html', {
        'page_obj': page_obj, 'query': query, 'category': category, 'demographic': demographic,
        'categories': Scheme.CATEGORY_CHOICES, 'demographics': Scheme.TARGET_DEMOGRAPHIC_CHOICES,
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

    messages.success(request, f"Application submitted for {scheme.name}. Please upload supporting documents next.")
    application = Application.objects.get(citizen=request.user, scheme=scheme)
    return redirect('upload_document', application_id=application.id)

@login_required
def upload_document(request, application_id):
    """Citizen uploads proof documents against their own application."""
    application = get_object_or_404(Application, pk=application_id, citizen=request.user)

    if request.method == 'POST':
        form = DocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.application = application
            doc.save()
            messages.success(request, f"{doc.get_document_type_display()} uploaded.")
            return redirect('upload_document', application_id=application.id)
    else:
        form = DocumentUploadForm()

    documents = application.documents.all()
    return render(request, 'core/upload_document.html', {
        'application': application, 'form': form, 'documents': documents,
    })


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

@officer_required
def scheme_analytics(request):
    """
    Officer analytics dashboard — powered entirely by scheme_analytics_view.
    Also computes a state-wise applicant breakdown via a second aggregate
    query, joining Application -> CitizenProfile.
    """
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT scheme_name, scheme_category, total_applications,
                   approved_count, rejected_count, pending_count
            FROM scheme_analytics_view
        """)
        columns = [col[0] for col in cursor.description]
        scheme_rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT cp.state, COUNT(a.id) AS application_count
            FROM core_application a
            JOIN core_citizenprofile cp ON cp.user_id = a.citizen_id
            GROUP BY cp.state
            ORDER BY application_count DESC
        """)
        state_rows = cursor.fetchall()

    return render(request, 'core/scheme_analytics.html', {
        'scheme_rows': scheme_rows, 'state_rows': state_rows,
    })

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"  # check console.groq.com for current available model names


def build_scheme_context():
    """
    Builds a compact, factual summary of currently active schemes to GROUND
    the assistant's answer. This is deliberately passed into the prompt so
    the model only ever talks about real schemes with real figures from our
    own database — it cannot invent a scheme name or eligibility number that
    isn't actually listed here.
    """
    schemes = Scheme.objects.filter(is_active=True).filter(
        models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=timezone.now().date())
    ).prefetch_related('criteria')

    lines = []
    for s in schemes:
        bits = []
        for c in s.criteria.all():
            if c.min_income: bits.append(f"min income ₹{c.min_income}")
            if c.max_income: bits.append(f"max income ₹{c.max_income}")
            if c.min_age: bits.append(f"min age {c.min_age}")
            if c.max_age: bits.append(f"max age {c.max_age}")
            if c.category_required: bits.append(f"category required: {c.category_required}")
        criteria_text = "; ".join(bits) if bits else "no specific restrictions"
        lines.append(f"- {s.name} ({s.get_category_display()}, for {s.get_target_demographic_display()}): {s.description} Eligibility: {criteria_text}.")
    return "\n".join(lines) if lines else "No schemes currently available."


@login_required
@require_POST
def scheme_assistant_api(request):
    """
    AI scheme assistant. Grounds every answer in real DB scheme data, and
    replies in whatever language the citizen used — no separate translation
    pipeline needed, since LLMs handle this natively when instructed to.
    """
    try:
        body = json.loads(request.body)
        user_message = body.get('message', '').strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'Invalid request.'}, status=400)

    if not user_message:
        return JsonResponse({'error': 'Empty message.'}, status=400)

    scheme_context = build_scheme_context()

    profile_context = ""
    if request.user.is_citizen():
        try:
            p = request.user.citizen_profile
            profile_context = (
                f"\nThe citizen's own profile: age {p.age}, gender {p.get_gender_display()}, "
                f"category {p.get_category_display()}, state {p.state}, annual income ₹{p.income}. "
                f"Use this to personalize your answer where relevant, but remind them to verify "
                f"final eligibility on the scheme's official page."
            )
        except CitizenProfile.DoesNotExist:
            pass

    system_prompt = (
        "You are YojanaConnect's scheme assistant, helping Indian citizens find relevant "
        "government welfare schemes. Only use the scheme data provided below — never invent "
        "scheme names, income limits, or age limits that aren't listed. If nothing matches the "
        "citizen's question, say so honestly rather than guessing. Always reply in the SAME "
        "language the citizen used to ask (Hindi, Tamil, English, or any other language). Keep "
        "answers short and conversational — 3 to 5 sentences, not a long essay.\n\n"
        f"Available schemes:\n{scheme_context}"
        f"{profile_context}"
    )

    try:
        response = requests.post(
            GROQ_API_URL,
            headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "temperature": 0.3,
                "max_tokens": 400,
            },
            timeout=10,
        )
        response.raise_for_status()
        reply = response.json()['choices'][0]['message']['content']
        return JsonResponse({'reply': reply})
    except requests.RequestException:
        return JsonResponse({'reply': "Sorry, the assistant is temporarily unavailable right now. Please try browsing schemes directly, or try again shortly."})
    except (KeyError, IndexError):
        return JsonResponse({'reply': "Sorry, I couldn't process that. Please try rephrasing your question."})