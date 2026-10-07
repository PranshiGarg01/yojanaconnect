# Changelog — YojanaConnect

All notable changes, fixes, enhancements, and assumptions made during development.

---

## Phase 0 — Audit and Fix What's Broken

### Bugs Found and Fixed
1. **Requirements Encoding & Missing Dependencies**:
   - `requirements.txt` was encoded as UTF-16LE with Byte Order Mark (BOM) and CRLF line breaks. This caused failure in docker/python tooling and prevented `requests` and `argon2-cffi` from installing in the virtual environment, raising `ModuleNotFoundError: No module named 'requests'`.
   - *Fix*: Re-encoded `requirements.txt` into standard UTF-8 with LF line endings, and installed all required packages including `argon2-cffi` and `requests`.
2. **Database Name Mismatch Across Project**:
   - The specification mandates the exact database name `YojanaConnect` (mixed case). However, `.env`, `.env.example`, `settings.py`, `docker-compose.yml`, and `ci.yml` had divergent identifiers (`YojanaConnect_DB` or `yojanaconnect_db`).
   - *Fix*: Created the `YojanaConnect` PostgreSQL database, updated `.env`, `.env.example`, `docker-compose.yml`, `settings.py`, `.github/workflows/ci.yml`, and `README.md` to reference `YojanaConnect` consistently.
3. **Docker Compose Healthcheck & Startup Order**:
   - On container startup, `web` would attempt running migrations before `db` (PostgreSQL) was ready to accept socket connections because `docker-compose.yml` lacked a healthcheck gate.
   - *Fix*: Added a PostgreSQL healthcheck (`pg_isready -U postgres -d YojanaConnect`) on the `db` service and configured `depends_on: { db: { condition: service_healthy } }` on `web`.
4. **Syntax Error in Citizen Dashboard Template**:
   - In `templates/core/dashboard_citizen.html`, line 36 contained an unclosed `<a href="...">` anchor tag wrapping `Browse All Schemes` without `</a>`.
   - *Fix*: Closed the anchor tag with `</a>`.
5. **Missing Mandi Prices Context in Citizen Dashboard**:
   - `core/views.py` `dashboard` view fetched `mandi_prices` via `fetch_mandi_prices()`, but failed to pass `mandi_prices` into the context dictionary for `dashboard_citizen.html`, leaving the table empty.
   - *Fix*: Included `'mandi_prices': mandi_prices` in the dashboard render context.
6. **Officer Dashboard Placeholder Dead-End**:
   - `templates/core/dashboard_officer.html` was an empty placeholder with no navigation or action cards.
   - *Fix*: Created a rich officer dashboard displaying real-time summary statistics (pending applications, total schemes, total applications) and recent applications table with direct links to review.
7. **Missing JSON API Endpoints**:
   - The project context specified `/api/my-applications/` (citizen-only) and `/api/scheme-stats/` (officer-only), which were missing from `core/views.py` and `core/urls.py`.
   - *Fix*: Implemented `my_applications_api` and `scheme_stats_api` with RBAC decorators/checks and mapped their routes.

### Assumptions Made
- Database name `YojanaConnect` was initialized directly in PostgreSQL and configured everywhere.
- API endpoints `/api/my-applications/` and `/api/scheme-stats/` use Django's session authentication and role validation (`is_citizen` and `is_officer`).
