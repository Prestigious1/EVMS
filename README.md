# EVMS — Electronic Venue Management System (LASU)

A Django-based web application for managing hall and venue reservations at Lagos State University. Supports role-based workflows for Students, Staff, Ventures, Facility Management, and Administrators.

## Features

- **13-stage reservation workflow** — SUBMITTED → FORWARDED → UNDER_REVIEW → AVAILABLE → APPROVED_PAYMENT → PAYMENT_PENDING → PAID → CONFIRMED → COMPLETED → INSPECTION_PENDING → DAMAGE_REPORTED → CLOSED / REJECTED / CANCELLED
- **Role-based access control** — STUDENT, STAFF, EXTERNAL, VENTURES, FACILITY, ADMIN
- **Conflict detection** — automated overlap checking with database-level indexes
- **Paystack integration** — secure online payments with receipt generation
- **Manual payment recording** — cash/bank transfer support for Ventures staff
- **Coupon engine** — percentage/fixed discounts with per-user limits, role/hall/faculty restrictions
- **Document management** — versioned uploads per reservation
- **Post-event inspection** — damage reporting and penalty enforcement
- **Analytics dashboard** — revenue breakdown, peak hours, most-used halls, exportable reports (CSV, XLSX, PDF)
- **Audit trail** — immutable status history, booking logs, and global audit entries
- **Notifications** — in-app inbox and email broadcasts via Mailgun/django-anymail

## Tech Stack

| Component | Version/Choice |
|-----------|---------------|
| Language | Python 3.11+ |
| Framework | Django 6.0.4 |
| Database | SQLite (dev) / PostgreSQL (prod recommended) |
| Payments | Paystack |
| Email | django-anymail (Mailgun) |
| Admin Theme | django-jazzmin 3.0.4 |
| Rich Text | django-ckeditor-5 |
| PDF | reportlab |
| Excel | openpyxl |
| Frontend | HTML5, Bootstrap 5, JavaScript, Chart.js, FullCalendar |

## Prerequisites

- Python 3.11 or higher
- pip
- Virtual environment tool (venv, virtualenv, etc.)

## Quick Start

### 1. Clone the repository

```bash
git clone <repository-url>
cd EVMS/source-code
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in `source-code/` (same directory as `manage.py`):

```env
DEBUG=True
SECRET_KEY=your-secret-key-here
DATABASE_URL=sqlite:///db.sqlite3

# Paystack (required for payments)
PAYSTACK_SECRET_KEY=sk_test_...
PAYSTACK_PUBLIC_KEY=pk_test_...
PAYSTACK_BASE_URL=https://api.paystack.co

# Email (optional — defaults to console backend in DEBUG mode)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
DEFAULT_FROM_EMAIL=no-reply@lasu.edu.ng

# Mailgun (production)
MAILGUN_API_KEY=...
MAILGUN_SENDER_DOMAIN=mg.lasu.edu.ng
```

### 5. Run migrations

```bash
python manage.py makemigrations users hall reservations
python manage.py migrate
```

### 6. Create a superuser

```bash
python manage.py createsuperuser
```

### 7. Collect static files (production)

```bash
python manage.py collectstatic --noinput
```

### 8. Run the development server

```bash
python manage.py runserver
```

Visit [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Project Structure

```
source-code/
├── hms_prj/                  # Django project settings, URLs, WSGI/ASGI
├── core/                     # AuditLog, Announcements, FAQ, Contact, error handlers
├── users/                    # Custom User, RoleCapability, LoginLog, auth views
├── hall/                     # Hall, HallImage, Facility, HallBlock, HallBookmark
├── reservations/             # Reservation workflow, WorkflowService, documents, inspections
├── payments/                 # Paystack integration, manual payments, receipts
├── notifications/            # Notification, BroadcastMessage, signals
├── reports/                  # Analytics dashboard, CSV/XLSX/PDF exports
├── templates/                # Shared HTML templates
│   ├── hall/                 # Base layout, public pages
│   ├── core/                 # Error pages
│   ├── reservations/         # Workflow dashboards
│   └── reports/              # Reports dashboard
└── requirements.txt
```

## Role Capabilities

| Role | Key Capabilities |
|------|-----------------|
| ADMIN | Full system control, user management, all reports |
| STAFF | Read-only access to bookings, payments, reports |
| STUDENT | Submit bookings, track own reservations, pay online |
| EXTERNAL | Same as Student (non-LASU users) |
| VENTURES | Review submissions, forward to Facility, approve for payment, quote prices, issue penalties, record manual payments |
| FACILITY | Confirm physical availability, open inspections, report damages, close bookings |

## Workflow Overview

1. **Applicant** submits a reservation with event details and supporting documents.
2. **Ventures** receives the submission and either reviews it internally or forwards it to Facility.
3. **Facility** confirms physical availability or rejects the request.
4. **Ventures** quotes the final price (with optional coupon) and approves for payment.
5. **Applicant** pays via Paystack (or Ventures records manual payment).
6. **Ventures** officially confirms the booking after payment verification.
7. After the event, **Facility** opens a post-event inspection.
8. Inspection results in PASSED, FAILED, or DAMAGE_REPORTED.
9. **Ventures** formally closes the booking.

## Development Commands

```bash
# Run migrations
python manage.py makemigrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run dev server
python manage.py runserver

# Collect static files
python manage.py collectstatic --noinput
```

## Deployment Notes

- Set `DEBUG=False` in production.
- Use PostgreSQL instead of SQLite for concurrent production workloads.
- Configure `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.
- Set up HTTPS (Let's Encrypt recommended).
- Use Gunicorn or Daphne behind Nginx as a reverse proxy.
- Configure `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE`.
- Store secrets in environment variables or a secrets manager; never commit `.env` files.

## License

This project was developed for Lagos State University (LASU) as an academic project.
