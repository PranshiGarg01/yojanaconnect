import os
import json
import logging
import requests
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank
from .models import Scheme

logger = logging.getLogger(__name__)


def retrieve_grounded_schemes(user_query, limit=6):
    """
    Retrieves the most relevant active schemes from PostgreSQL to ground
    the LLM context, preventing hallucinations.
    """
    today = timezone.now().date()
    qs = Scheme.objects.filter(is_active=True).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=today)
    ).prefetch_related('criteria')

    clean_query = user_query.strip()
    if clean_query:
        try:
            vector = SearchVector('name', weight='A') + SearchVector('description', weight='B')
            search_query = SearchQuery(clean_query)
            results = qs.annotate(rank=SearchRank(vector, search_query)).filter(
                Q(rank__gte=0.01) | Q(name__icontains=clean_query) | Q(description__icontains=clean_query)
            ).order_by('-rank')[:limit]
            if not results.exists():
                results = qs.order_by('name')[:limit]
        except Exception:
            results = qs.filter(
                Q(name__icontains=clean_query) | Q(description__icontains=clean_query)
            )[:limit]
            if not results.exists():
                results = qs.order_by('name')[:limit]
    else:
        results = qs.order_by('name')[:limit]

    grounded_data = []
    for s in results:
        criteria_info = []
        for c in s.criteria.all():
            parts = []
            if c.min_income: parts.append(f"Min Income ₹{c.min_income}")
            if c.max_income: parts.append(f"Max Income ₹{c.max_income}")
            if c.min_age: parts.append(f"Min Age {c.min_age}")
            if c.max_age: parts.append(f"Max Age {c.max_age}")
            if c.category_required: parts.append(f"Category {c.get_category_required_display()}")
            if c.gender_required: parts.append(f"Gender {c.get_gender_required_display()}")
            criteria_info.append(f"Group {c.criteria_group}: " + (", ".join(parts) or "Open"))

        grounded_data.append({
            'name': s.name,
            'category': s.get_category_display(),
            'target_demographic': s.get_target_demographic_display(),
            'description': s.description,
            'official_url': s.official_reference_url,
            'criteria': "; ".join(criteria_info) or "No restrictions",
        })
    return grounded_data


def generate_scheme_response(user_message, user=None):
    """
    Main orchestrator:
    1. Retrieves real scheme context from PostgreSQL.
    2. Calls LLM API (Google Gemini or Groq) with grounding instructions.
    3. Responds in the citizen's own language.
    4. Provides clean fallback if API key is not configured or network fails.
    """
    grounded_schemes = retrieve_grounded_schemes(user_message)
    sources = [{'name': s['name'], 'url': s['official_url']} for s in grounded_schemes]

    context_str = "\n\n".join([
        f"Scheme: {s['name']}\nCategory: {s['category']} | Target: {s['target_demographic']}\n"
        f"Description: {s['description']}\nEligibility Criteria: {s['criteria']}\nOfficial URL: {s['official_url']}"
        for s in grounded_schemes
    ])

    system_prompt = (
        "You are YojanaConnect AI, a helpful, respectful, and authoritative advisory assistant "
        "for Indian welfare schemes. Your role is to help citizens discover and understand government schemes.\n\n"
        "STRICT GROUNDING RULES:\n"
        "1. Base your answer EXCLUSIVELY on the verified scheme records provided in the CONTEXT below.\n"
        "2. Do NOT invent scheme names, figures, eligibility thresholds, or benefits.\n"
        "3. MULTILINGUAL RULE: Respond in the EXACT SAME LANGUAGE and script used by the citizen "
        "(e.g., Hindi, Tamil, Telugu, Bengali, Marathi, Gujarati, Kannada, Malayalam, or English).\n"
        "4. Keep explanations clear, friendly, and structured. Always cite the official portal URL.\n"
    )

    full_prompt = (
        f"{system_prompt}\n\n"
        f"--- OFFICIAL DATABASE CONTEXT ---\n{context_str}\n\n"
        f"--- CITIZEN QUESTION ---\n{user_message}\n\n"
        f"Please provide your grounded response:"
    )

    gemini_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
    groq_key = os.environ.get('GROQ_API_KEY')

    # 1. Try Google Gemini API
    if gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
            payload = {
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 800}
            }
            resp = requests.post(url, json=payload, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                text = data['candidates'][0]['content']['parts'][0]['text']
                return {'reply': text, 'sources': sources, 'provider': 'gemini'}
        except Exception as e:
            logger.warning("Gemini API call failed: %s", e)

    # 2. Try Groq API (fallback free provider)
    if groq_key:
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
            payload = {
                "model": "llama-3.1-8b-instant",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"CONTEXT:\n{context_str}\n\nQUESTION:\n{user_message}"}
                ],
                "temperature": 0.2,
                "max_tokens": 800,
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                text = data['choices'][0]['message']['content']
                return {'reply': text, 'sources': sources, 'provider': 'groq'}
        except Exception as e:
            logger.warning("Groq API call failed: %s", e)

    # 3. Resilient Grounded Fallback (when offline or before LLM API key configured)
    reply_lines = [
        "Namaste! Based on your query and our official government database records, here are the most relevant schemes:\n"
    ]
    for s in grounded_schemes[:4]:
        reply_lines.append(
            f"• **{s['name']}** ({s['category']})\n"
            f"  {s['description']}\n"
            f"  *Eligibility*: {s['criteria']}\n"
            f"  *Official Portal*: {s['official_url']}\n"
        )
    reply_lines.append(
        "\n*(Note: Running with verified database grounding. To activate real-time LLM generative chat, set `GEMINI_API_KEY` or `GROQ_API_KEY` in `.env`)*"
    )

    return {'reply': "\n".join(reply_lines), 'sources': sources, 'provider': 'local_grounded'}
