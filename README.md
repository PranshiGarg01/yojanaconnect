# YojanaConnect

A Government Welfare Scheme Eligibility & Application Tracking System 

## Tech Stack
- Backend: Django (Python)
- Database: PostgreSQL
- Frontend: Django Templates + Bootstrap

## Setup
1. Clone the repo
2. `python -m venv venv` then `venv\Scripts\activate`
3. `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and fill in your PostgreSQL password
5. Create a PostgreSQL database named `yojanaconnect_db`
6. `python manage.py migrate`
7. `python manage.py runserver`
