# EVMS — Event Hall Management System (LASU)

> **Electronic Venue Management System** for Lagos State University — a full-featured Django web application for managing hall and venue reservations with a multi-role approval workflow, Bursary payment verification, post-event inspections, and a comprehensive role-scoped BI analytics centre.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Data Models](#data-models)
- [Roles & Capabilities](#roles--capabilities)
- [Booking Lifecycle](#booking-lifecycle)
- [URL Endpoints](#url-endpoints)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [Development Commands](#development-commands)
- [Business Logic Rules](#business-logic-rules)
- [Deployment Notes](#deployment-notes)
- [License](#license)

---

## Overview

**System Name:** Event Hall Management System (EVMS)  
**Institution:** Lagos State University (LASU)  
**Developer:** Ajibade Alli Akinkunmi (Matric: 220591056)  
**Supervisor:** Prof. Aribisala Benjamin Segun  
**Department:** Computer Science, Faculty of Computing and Information Technology

EVMS is a web-based hall booking platform that enables students, staff, departments, and external users to reserve event halls at LASU. It enforces a structured multi-stage approval workflow coordinated across Ventures, Facility, and Bursary units — with manual payment proof submission, online payments via Paystack, detailed inspection reports, and a fully exportable BI analytics centre.

---

## Features

### Core Booking Engine
- **22-stage `BookingCaseStatus` lifecycle** — full canonical workflow from `DRAFT` through `CASE_CLOSED` (see [Booking Lifecycle](#booking-lifecycle))
- **Legacy `ReservationStatus` preserved** — backward-compatible 14-status enum retained alongside the new status system
- **Conflict detection** — checks against other `Reservation` records, `HallBlock` date ranges, and `InternalReservation` slots
- **Internal Reservations** — no-payment university-internal hall blocks (departments/faculties), tracked in reports and calendar
- **Booking permit & QR code** — auto-generated `qr_verification_code` on `BOOKING_APPROVED`; permit PDF downloadable
- **Availability API** — JSON endpoint for real-time calendar slot checking

### Users & Access Control
- **8 roles** — `STUDENT`, `STAFF`, `EXTERNAL`, `DEPARTMENT`, `VENTURES`, `FACILITY`, `BURSARY`, `ADMIN`
- **Database-driven `RoleCapability`** — capabilities seeded via management command; `can(user, capability)` helper
- **`LoginLog`** — IP address and user-agent tracking per login for security auditing
- **`can_submit_booking()`** — pre-submission eligibility check (blocked account, unpaid liabilities)
- **Auto-role assignment** — `@lasu.edu.ng` emails receive `STUDENT` role automatically
- **Superuser → ADMIN** — `is_superuser` flag automatically promotes role to `ADMIN` on save

### Hall Catalog
- **Hall categories** — Lecture Hall, Conference Hall, Seminar Room, Social Event Hall, Multipurpose Hall, Outdoor Space
- **Pricing** — `daily_rate`, `extra_hour_charge`, `security_deposit` per hall
- **Amenities** — `Amenity` + `HallAmenity` junction table; Bootstrap icon per amenity
- **Gallery** — `HallImage` with `is_cover` flag, `display_order`, atomic cover-swap
- **Hall status** — `is_active` / `is_archived` with admin restore
- **`HallBlock`** — date-range blocks (maintenance, special events) created by Facility or Admin
- **Bookmarks** — `HallBookmark` per user/hall pair
- **Owner department** — `VENTURES` or `FACILITY` ownership tag per hall
- **Rules & Terms** — displayed to applicants before booking

### Coupon Engine
- **`Coupon` model** (in `payments` app) — percentage or fixed discounts
- **Restrictions** — min booking amount, max discount cap, total/per-user usage limits, validity dates
- **Targeting** — applicable halls (M2M), applicable categories (JSON), faculty/department/role restrictions
- **Stackable flag** — `is_stackable` boolean
- **Workflow coupon decision** — Ventures approves / rejects / replaces / removes coupon requests; tracked in `CouponActionLog`
- **Coupon snapshot** — full coupon rules saved on reservation at request time for audit trail

### Payment Authorization Stage
- **`PaymentAuthorization` model** — Ventures creates financial breakdown before dispatching payment request
- **Financial breakdown** — hall price, security deposit, extra charges, penalty amount, coupon discount, VAT, total
- **Payment deadline** — 24h / 48h / 72h / custom; extendable; `DeadlineExtensionLog` for every change
- **Expiry** — `PAYMENT_EXPIRED` case status when deadline passes without payment

### Payments & Payment Proofs
- **Paystack online payments** — `Payment` model; card and transfer methods; server-side callback verification
- **Manual payment proof** — `PaymentProof` model; applicant uploads receipt/bank evidence file + transaction ref
- **Bursary verification** — Bursary reviews proofs, adds `bursary_notes`, marks `VERIFIED` or `REJECTED`
- **Damage payment proof** — separate proof submission for post-event damage fees
- **PDF receipts** — generated via ReportLab (`receipt_pdf.py`)

### Documents
- **`ReservationDocument`** — versioned uploads (Authorization Letter, Permit, Image, Payment Proof, Damage Payment Proof, Other)
- **Visibility routing** — per-document `visible_to` field (comma-separated: `APPLICANT`, `VENTURES`, `BURSARY`; Facility excluded by design)
- **`DocumentType`** choices enforced at upload

### Communication System
- **`CommunicationThread`** — one thread per reservation (OneToOne)
- **`ThreadMessage`** — typed messages: `APPLICANT_VISIBLE`, `INTERNAL`, `SYSTEM_GENERATED`
- **`ThreadAttachment`** — file attachments per message
- **`MessageReadStatus`** — per-user read tracking
- **`target_roles`** — comma-separated role routing per message (e.g. `VENTURES,BURSARY,APPLICANT`)
- **Legacy `ReservationMessage`** — retained for backward compatibility

### Post-Event Inspection
- **`HallInspectionReport`** — structured ratings: hall condition, cleanliness, furniture, equipment
- **`ConditionRating`** — Excellent / Good / Fair / Poor / Damaged
- **`InspectionOutcome`** — No Damage — Clear, or Damage Found
- **`InspectionPhoto`** — photo evidence per inspection
- **`InspectionReminder`** — tracks automated reminder notifications sent to Facility (up to 3 reminder levels)
- **Legacy `HallInspection`** — simple Passed/Failed/Damage Reported; retained for old records

### Damage Reports & Penalties
- **`DamageReport`** — description, affected items, cost estimate, assessment officer, invoice generation flag
- **`DamagePhoto`** + **`DamageDocument`** — photo and documentary evidence for damage cases
- **Admin waiver** — `is_forgiven`, `waived_by`, `admin_waiver_reason`
- **`Penalty`** — title, description, amount, paid/forgiven flags
- **`VenturesPenaltyRecord`** — links a penalty to a booking case with type: Penalty / Administrative Fee / Late Charge / Additional Charge

### Booking Audit Trail
- **`BookingTimeline`** — 35+ typed `TimelineEventType` entries (submitted, reviewed, forwarded, coupon action, payment events, inspection, damage, closed, etc.)
- **`BookingStatusHistory`** — immutable log of every status transition (previous → new, actor, notes)
- **`BookingLog`** — freeform per-reservation action log

### Notifications
- **`Notification`** — per-user inbox with `notification_type`, priority, optional link, `is_read`
- **`BroadcastMessage`** — admin-created messages targeting a role or all users, optional file attachment

### Core Utilities
- **`AuditLog`** — global system-wide action log (user, role, action, model, old/new value, IP)
- **`ActivityLog`** — lighter activity tracking (user, role, action, IP, affected object)
- **`Announcement`** — rich-text announcements with image, video, file attachment, view/unique-view counters
- **`FAQ`** — active/inactive frequently asked questions
- **`ContactMessage`** — contact form with `admin_reply` field + email notification

### Reports & Analytics (BI Centre)

The `reports/` app provides a full Business Intelligence centre with role-scoped dashboards and 14 dedicated report modules, all powered by a centralised Universal Report Engine.

#### Universal Report Engine (`reports/engine.py`)
- **Date-range filtering** — 12 period presets: Today, Yesterday, Last 7 Days, Last 30 Days, This Month, Last Month, This Quarter, This Year, Last Year, Academic Session, Semester, Custom Range
- **Advanced search & filtering** — per-model search helpers for bookings, payments, payment proofs, audit logs, and users
- **Sorting & pagination** — configurable sort fields with ascending/descending toggle
- **Export engine** — unified `export_to_csv()`, `export_to_xlsx()`, `export_to_pdf()` helpers used across all report views
- **Role-scope guard** — `get_role_scope()` and `can_access_report()` ensure every report view enforces RBAC

#### Role-Scoped BI Dashboards

| URL | Dashboard | Accessible By |
|-----|-----------|---------------|
| `reports/` | Auto-redirect to role dashboard | All report-enabled roles |
| `reports/dashboard/admin/` | Admin overview — KPIs, charts, audit, pending actions | Admin / Staff |
| `reports/dashboard/ventures/` | Ventures — booking pipeline, coupon stats, revenue | Ventures / Admin |
| `reports/dashboard/facility/` | Facility — inspection queue, hall usage, blocks | Facility / Admin |
| `reports/dashboard/bursary/` | Bursary — payment verification queue, revenue | Bursary / Admin |
| `reports/dashboard/` | Legacy entry — redirects to role dashboard | All |

#### Report Modules (14 modules)

| URL | Report | Scope |
|-----|--------|-------|
| `reports/centre/` | Report Centre — unified search across all categories | All |
| `reports/bookings/` | Booking Reports — full listing with status & date filters | full, ventures, facility |
| `reports/payments/` | Payment Reports — payment methods, verification status | full, ventures, bursary |
| `reports/revenue/` | Revenue Reports — totals, trends, by hall / period | full, ventures, bursary |
| `reports/coupons/` | Coupon Reports — usage, discount totals, approval status | full, ventures |
| `reports/damage/` | Damage Reports — descriptions, costs, waiver status | full, facility, bursary |
| `reports/inspections/` | Inspection Reports — outcomes, ratings, photos | full, facility |
| `reports/penalties/` | Penalty Reports — amounts, paid/forgiven breakdown | full, ventures, bursary |
| `reports/halls/` | Hall Reports — utilisation, availability, category | full, facility |
| `reports/applicants/` | Applicant Reports — role distribution, booking history | full, ventures |
| `reports/management/` | Management Reports — staff actions, workflow throughput | full |
| `reports/notifications/` | Notification Reports — broadcast & inbox analytics | full |
| `reports/communications/` | Communication Reports — thread & message activity | full, ventures |
| `reports/audit/` | Audit Reports — system-wide action log with full search | full |
| `reports/system-usage/` | System Usage Reports — login trends, active users | full |

#### Export Endpoints

| URL | Format | Description |
|-----|--------|-------------|
| `reports/export/` | CSV / XLSX / PDF | Universal export — accepts `type`, `format`, `period` params |
| `reports/export/reservations.csv` | CSV | All reservations bulk export |
| `reports/export/payments.csv` | CSV | All payments bulk export |
| `reports/export/dashboard.pdf` | PDF | Dashboard summary PDF |
| `reports/export/users/csv/` | CSV | User roster (Admin only) |
| `reports/export/logs/csv/` | CSV | Audit / activity / login logs (Admin only) |
| `reports/export/<report_type>.xlsx` | XLSX | Per-module Excel export |

### Calendar
- **`/reservations/calendar/`** — visual calendar view
- **`/reservations/calendar/events/`** — JSON feed of events for FullCalendar integration

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ |
| Framework | Django 6.0.4 |
| Database | SQLite (dev) / PostgreSQL (prod recommended) |
| Payments | Paystack |
| Email | django-anymail 14.0 (Mailgun) |
| Admin Theme | django-jazzmin 3.0.4 |
| Rich Text | django-ckeditor / django-ckeditor-5 |
| Forms | django-crispy-forms 2.5 |
| PDF | ReportLab 4.4.10 |
| Excel | openpyxl 3.1.5 |
| QR Code | qrcode 8.2 |
| Image Processing | Pillow 12.2.0 |
| Frontend | HTML5, Bootstrap 5, JavaScript, Chart.js, FullCalendar |
| Config | python-dotenv / environs |
| Data Import/Export | django-import-export 4.4.0 + tablib |
| Math Filters | django-mathfilters |
| Tagging | django-taggit |
| DB URL Parsing | dj-database-url |
| File Type Detection | filetype |

---

## Project Structure

```
source-code/
├── hms_prj/                        # Django project settings, URLs, WSGI/ASGI
│   ├── settings.py
│   ├── urls.py                     # Root URL configuration (6 app includes)
│   ├── wsgi.py
│   └── asgi.py
├── core/                           # Global utilities
│   ├── models.py                   # AuditLog, ActivityLog, FAQ, ContactMessage, Announcement
│   ├── services.py                 # create_audit_log(), can_view_reports() helper
│   ├── context_processors.py       # Template context injections
│   └── views.py                    # Custom 403/404/500 handlers, system logs view
├── users/                          # User management
│   ├── models.py                   # User, UserRole (8 roles), RoleCapability, LoginLog
│   ├── services.py                 # can(), can_manage_bursary(), can_submit_booking(), record_login()
│   ├── decorators.py               # Role-based view decorators
│   ├── admin_views.py              # Admin-only user management views
│   └── management/commands/
│       └── seed_capabilities.py    # Seed all role capabilities to DB
├── hall/                           # Hall catalog
│   ├── models.py                   # Hall, HallImage, Amenity, HallAmenity, HallBookmark, HallBlock
│   ├── forms.py                    # Hall booking & search forms
│   └── views.py                    # Public hall pages, dashboards, bookmarks, HallBlock API
├── reservations/                   # Booking engine
│   ├── models.py                   # Reservation, BookingCaseStatus (22), BookingTimeline,
│   │                               # CommunicationThread, ThreadMessage, ThreadAttachment,
│   │                               # MessageReadStatus, DamageReport, DamagePhoto, DamageDocument,
│   │                               # Penalty, VenturesPenaltyRecord, BookingStatusHistory, BookingLog,
│   │                               # ReservationDocument, HallInspectionReport, InspectionPhoto,
│   │                               # HallInspection (legacy), InternalReservation,
│   │                               # PaymentAuthorization, DeadlineExtensionLog, CouponActionLog,
│   │                               # InspectionReminder, ReservationMessage (legacy)
│   ├── services.py                 # WorkflowService — state guards & transitions
│   ├── action_engine.py            # Atomic workflow action dispatcher
│   ├── signals.py                  # Auto-notifications on messages, documents, inspections
│   ├── forms.py                    # Reservation, inspection, penalty, message forms
│   ├── pdf.py                      # Booking permit PDF generation
│   └── views.py                    # All workflow views (ventures, facility, bursary, admin)
├── payments/                       # Payment processing
│   ├── models.py                   # Coupon, Payment, PaymentProof
│   ├── paystack.py                 # Paystack API wrapper
│   ├── paystack_utils.py           # Paystack utilities
│   ├── services.py                 # Payment service helpers
│   ├── receipt_pdf.py              # PDF receipt generation
│   └── views.py                    # Paystack callbacks, manual payments, coupon management
├── notifications/                  # Notifications
│   ├── models.py                   # Notification, BroadcastMessage
│   └── signals.py                  # Auto-notification triggers
├── reports/                        # Analytics & BI centre
│   ├── engine.py                   # Universal Report Engine — filtering, search, sort, export
│   ├── pdf.py                      # Dashboard PDF builder (ReportLab)
│   ├── urls.py                     # 20 report/export URL patterns
│   └── views.py                    # 5 BI dashboards + 14 report modules + export views
├── templates/
│   ├── hall/                       # Base layout, public pages, role dashboards
│   ├── core/                       # Error pages (403, 404, 500)
│   ├── reservations/               # Workflow dashboards & detail templates
│   ├── notifications/              # Notification inbox
│   ├── payments/                   # Payment pages
│   ├── reports/                    # BI dashboards (5) + report module templates (14) + base
│   └── users/                      # Auth, profile, admin user views
├── static/                         # CSS, JS, images
├── media/                          # User-uploaded files
├── requirements.txt
├── manage.py
├── create_su.py                    # Superuser creation script
├── test_auth.py                    # Auth unit tests
├── test_dashboard.py               # Dashboard unit tests
└── .env.example                    # Environment variable template
```

---

## Data Models

### `users` App

| Model | Purpose |
|-------|---------|
| `User` | Custom `AbstractUser`; fields: `email`, `phone_number`, `role`, `department`, `profile_image`, `is_verified`, `is_blocked` |
| `RoleCapability` | DB-driven capability assignments per role (unique `role` + `capability`) |
| `LoginLog` | Per-login security record: user, IP address, user-agent |

### `hall` App

| Model | Purpose |
|-------|---------|
| `Hall` | Core hall record: name, category, capacity, faculty, building, pricing, rules, terms, owner department |
| `HallImage` | Gallery images per hall; `is_cover` flag enforced atomically; `display_order` |
| `Amenity` | Global amenity catalogue with Bootstrap icon class |
| `HallAmenity` | Junction: Hall ↔ Amenity |
| `HallBookmark` | User-saved hall favourites |
| `HallBlock` | Admin/Facility date-range block (maintenance, events) |

### `reservations` App

| Model | Purpose |
|-------|---------|
| `Reservation` | Core booking: hall, user, dates/times, `case_status` (22 stages), `status` (legacy), financials, coupon fields, QR code |
| `BookingTimeline` | Append-only timeline: 35+ typed events with actor, role, description |
| `CommunicationThread` | One-to-one thread per reservation |
| `ThreadMessage` | Typed messages (Applicant Visible / Internal / System); `target_roles` routing; reply threading; mentions |
| `ThreadAttachment` | Files attached to thread messages |
| `MessageReadStatus` | Per-user read timestamps |
| `ReservationDocument` | Versioned uploads (6 types) with `visible_to` role routing |
| `DamageReport` | Damage description, affected items, cost estimate, waiver, assessment officer, photos |
| `DamagePhoto` | Photo evidence for a damage report |
| `DamageDocument` | Supporting documents for a damage report |
| `Penalty` | Financial penalty (title, amount, paid/forgiven) |
| `VenturesPenaltyRecord` | Adds penalty type context (Penalty / Admin Fee / Late Charge / Additional) |
| `BookingStatusHistory` | Immutable status-change log (previous → new, actor, notes) |
| `BookingLog` | Freeform per-reservation action log |
| `ReservationMessage` | Legacy messaging (backward compat) |
| `HallInspectionReport` | Structured post-event report: condition ratings for hall, cleanliness, furniture, equipment |
| `InspectionPhoto` | Photos attached to an inspection report |
| `HallInspection` | Legacy inspection (Passed/Failed/Damage Reported) |
| `InternalReservation` | University-internal hall use — no payment, blocks availability |
| `PaymentAuthorization` | Ventures financial breakdown: pricing, discounts, VAT, deadline, coupon decision |
| `DeadlineExtensionLog` | Audit record of every payment deadline extension/shortening |
| `CouponActionLog` | Immutable log of every coupon action per booking |
| `InspectionReminder` | Tracks Facility reminder notifications (up to 3 levels) |

### `payments` App

| Model | Purpose |
|-------|---------|
| `Coupon` | Discount codes: percentage or fixed; hall/role/faculty/department restrictions; usage limits |
| `Payment` | Paystack payment record linked to reservation, damage report, or penalty |
| `PaymentProof` | Manual payment evidence (receipt file, transaction ref, amount claimed); verified by Bursary |

### `notifications` App

| Model | Purpose |
|-------|---------|
| `Notification` | Per-user inbox item: title, message, type, priority, link, `is_read` |
| `BroadcastMessage` | Admin broadcasts: role-targeted or all-user; optional attachment |

### `core` App

| Model | Purpose |
|-------|---------|
| `AuditLog` | System-wide action log: user, role, action, model, old/new value, IP address |
| `ActivityLog` | Lighter activity tracking per user action |
| `Announcement` | Rich-text announcements with image, video, attachment; view/unique-view counters |
| `FAQ` | Active/inactive FAQ entries |
| `ContactMessage` | Contact form submissions with admin reply capability |

---

## Roles & Capabilities

The system has **8 roles** defined in `users.models.UserRole`:

| Role | Description | Key Capabilities |
|------|-------------|-----------------|
| **ADMIN** | Full system control | All capabilities; overrides all permission checks; Django admin access |
| **STAFF** | Read-only oversight | `view_reports`, read-only access to bookings, payments |
| **STUDENT** | LASU applicant | Submit reservations, pay online, track own bookings, upload documents |
| **EXTERNAL** | Non-LASU applicant | Same as Student |
| **DEPARTMENT** | University department | Department-level bookings, `view_reports` |
| **VENTURES** | Booking management unit | `manage_payments`, `manage_coupons`, `manage_communications`, `view_financial_reports`, coupon decisions, pricing, penalties, payment authorization |
| **FACILITY** | Physical management unit | `manage_halls`, `manage_amenities`, `manage_hall_blocks`, `manage_inspections`, `manage_internal_reservations`, facility approval/rejection |
| **BURSARY** | Payment verification | `bursary_workflow`, `view_audit_history`, `generate_verification_reports` — reviews and approves/rejects payment proofs |

### Role-Specific Dashboards

| Role | Operational Dashboard | BI / Reports Dashboard |
|------|----------------------|------------------------|
| Student / External | `hall/dashboard.html` | — |
| Staff | `hall/staff_dashboard.html` | `reports/dashboard_admin.html` (read-only) |
| Department | `hall/department_dashboard.html` | — |
| Ventures Unit | `reservations/ventures_dashboard.html` | `reports/dashboard_ventures.html` |
| Facility Unit | `reservations/facility_dashboard.html` | `reports/dashboard_facility.html` |
| Bursary Unit | `reservations/bursary_dashboard.html` | `reports/dashboard_bursary.html` |
| System Admin | `reservations/admin_dashboard.html` | `reports/dashboard_admin.html` |

> Role access is enforced server-side on every view. Navigation dynamically shows only the relevant links per role.

---

## Booking Lifecycle

### Canonical `BookingCaseStatus` (22 stages)

```
DRAFT
  └─► SUBMITTED
          └─► UNDER_VENTURES_REVIEW
                    ├─► UNDER_FACILITY_REVIEW
                    │         ├─► FACILITY_APPROVED
                    │         │         └─► PAYMENT_AUTHORIZATION  ◄─── Ventures sets price + deadline
                    │         │                   ├─► PAYMENT_EXPIRED   (deadline passed)
                    │         │                   └─► AWAITING_PAYMENT
                    │         │                             └─► PAYMENT_SUBMITTED  ◄── applicant uploads proof
                    │         │                                       └─► UNDER_BURSARY_VERIFICATION
                    │         │                                                 ├─► PAYMENT_REJECTED  ──► back to AWAITING_PAYMENT
                    │         │                                                 └─► PAYMENT_VERIFIED
                    │         │                                                           └─► AWAITING_FINAL_APPROVAL
                    │         │                                                                     ├─► BOOKING_APPROVED  ◄── QR code generated
                    │         │                                                                     └─► BOOKING_REJECTED
                    │         └─► FACILITY_REJECTED  ──► BOOKING_REJECTED
                    └─► (direct) BOOKING_REJECTED / CASE_CLOSED

After BOOKING_APPROVED:
  └─► EVENT_COMPLETED
          └─► UNDER_POST_EVENT_INSPECTION  ◄── Facility opens inspection
                    ├─► DAMAGE_ASSESSED
                    │         ├─► AWAITING_DAMAGE_PAYMENT
                    │         │         └─► DAMAGE_PAYMENT_SUBMITTED
                    │         │                   └─► UNDER_DAMAGE_PAYMENT_VERIFICATION
                    │         │                             └─► DAMAGE_PAYMENT_VERIFIED
                    │         │                                       └─► CASE_CLOSED
                    │         └─► (forgiven) ──► CASE_CLOSED
                    └─► (no damage) ──► CASE_CLOSED

Any stage: USER_RESTRICTED
```

### Legacy `ReservationStatus` (retained for backward compatibility)

`SUBMITTED` → `FORWARDED` → `UNDER_REVIEW` → `AVAILABLE` → `APPROVED_PAYMENT` → `PAYMENT_PENDING` → `PAID` → `CONFIRMED` → `COMPLETED` → `INSPECTION_PENDING` → `DAMAGE_REPORTED` → `CLOSED` / `REJECTED` / `CANCELLED` (+ `PENDING`, `APPROVED` aliases)

---

## URL Endpoints

### Root URL mapping

| Prefix | App |
|--------|-----|
| `/` | `hall` (public pages, dashboards, calendar) |
| `/users/` | `users` (auth, profile, admin user management) |
| `/reservations/` | `reservations` (booking workflow) |
| `/payments/` | `payments` (Paystack, proofs, coupons) |
| `/notifications/` | `notifications` (inbox, broadcasts) |
| `/reports/` | `reports` (BI dashboards, report modules, exports) |
| `/system/logs/` | `core` (system log viewer — Admin only) |
| `/admin/` | Django Admin (Jazzmin theme) |

### `reservations/` app

| Method | URL | View | Description |
|--------|-----|------|-------------|
| GET | `my/` | `my_reservations` | Applicant's own reservation list |
| GET/POST | `create/<hall_id>/` | `create_reservation` | Submit a new reservation |
| GET | `availability/` | `availability_api` | JSON slot availability check |
| GET | `receipt/<booking_reference>/` | `receipt_pdf` | Download PDF receipt |
| GET | `verify/<booking_reference>/` | `verify_reservation` | QR/public booking verification page |
| GET | `calendar/` | `calendar_view` | Visual hall calendar |
| GET | `calendar/events/` | `calendar_events` | FullCalendar JSON event feed |
| GET | `ventures/` | `ventures_dashboard` | Ventures workflow dashboard |
| GET | `facility/` | `facility_dashboard` | Facility workflow dashboard |
| GET | `admin-dashboard/` | `admin_dashboard` | Admin overview dashboard |
| GET | `bursary/` | `bursary_dashboard` | Bursary payment verification queue |
| GET | `bursary/audit-logs/` | `bursary_audit_logs` | Bursary audit log with search |
| POST | `ventures/action/<ref>/` | `ventures_action` | Ventures workflow actions |
| POST | `facility/action/<ref>/` | `facility_action` | Facility workflow actions |
| POST | `bursary/action/<ref>/` | `bursary_action` | Bursary verify/reject payment proof |
| POST | `admin/action/<ref>/` | `admin_booking_action` | Admin override actions |
| GET | `detail/<ref>/` | `reservation_detail` | Full booking detail + tabs |
| POST | `upload-document/<ref>/` | `upload_document` | Upload reservation document |
| POST | `cancel/<ref>/` | `cancel_reservation` | Applicant cancellation |
| POST | `message/<ref>/` | `add_message` | Add legacy message |
| POST | `thread/message/<ref>/` | `add_thread_message` | Add thread message |
| POST | `payment-proof/<ref>/` | `submit_payment_proof` | Upload booking payment evidence |
| POST | `damage-payment-proof/<ref>/` | `submit_damage_payment_proof` | Upload damage payment evidence |
| GET/POST | `inspection/<ref>/` | `record_inspection` | Legacy inspection record |
| GET/POST | `inspection-report/<ref>/` | `record_inspection_report` | Full structured inspection report |
| GET | `penalties/` | `penalty_list` | Penalty management list |
| POST | `penalty/<id>/forgive/` | `forgive_penalty` | Admin forgive a penalty |
| GET/POST | `ventures/penalty/create/<ref>/` | `ventures_create_penalty_view` | Ventures create penalty |
| POST | `coupon/validate/` | `validate_coupon` | AJAX coupon validation |
| POST | `coupon/apply/<ref>/` | `apply_coupon` | Apply coupon to reservation |
| GET | `payment-auth/<ref>/` | `payment_authorization_page` | Payment Authorization form |
| POST | `payment-auth/<ref>/submit/` | `submit_payment_authorization` | Ventures submit payment auth |
| POST | `payment-auth/<ref>/extend-deadline/` | `extend_payment_deadline` | Extend payment deadline |
| POST | `admin/forgive/<ref>/` | `admin_forgive_liability_view` | Admin forgive liability |
| GET | `internal/` | `internal_list` | Internal reservation list |
| GET/POST | `internal/create/` | `internal_create` | Create internal reservation |
| GET/POST | `internal/<ref>/edit/` | `internal_edit` | Edit internal reservation |
| POST | `internal/<ref>/action/` | `internal_action` | Approve/reject internal reservation |

### `reports/` app

| URL | View | Description |
|-----|------|-------------|
| `reports/` | `reports_home` | Auto-redirect to role-specific BI dashboard |
| `reports/dashboard/` | `admin_reports_dashboard` | Legacy entry (redirects by role) |
| `reports/dashboard/admin/` | `dashboard_admin` | Admin full-system BI dashboard |
| `reports/dashboard/ventures/` | `dashboard_ventures` | Ventures BI dashboard |
| `reports/dashboard/facility/` | `dashboard_facility` | Facility BI dashboard |
| `reports/dashboard/bursary/` | `dashboard_bursary` | Bursary BI dashboard |
| `reports/centre/` | `report_centre` | Report Centre (unified search & filter) |
| `reports/bookings/` | `report_bookings` | Booking reports |
| `reports/payments/` | `report_payments` | Payment reports |
| `reports/revenue/` | `report_revenue` | Revenue reports |
| `reports/coupons/` | `report_coupons` | Coupon reports |
| `reports/damage/` | `report_damage` | Damage reports |
| `reports/inspections/` | `report_inspections` | Inspection reports |
| `reports/penalties/` | `report_penalties` | Penalty reports |
| `reports/halls/` | `report_halls` | Hall utilisation reports |
| `reports/applicants/` | `report_applicants` | Applicant reports |
| `reports/management/` | `report_management` | Management reports |
| `reports/notifications/` | `report_notifications` | Notification reports |
| `reports/communications/` | `report_communications` | Communication reports |
| `reports/audit/` | `report_audit` | Audit log reports |
| `reports/system-usage/` | `report_system_usage` | System usage reports |
| `reports/export/` | `universal_export` | Universal export (CSV/XLSX/PDF) |
| `reports/export/reservations.csv` | `export_reservations_csv` | Bulk reservations CSV |
| `reports/export/payments.csv` | `export_payments_csv` | Bulk payments CSV |
| `reports/export/dashboard.pdf` | `export_dashboard_pdf` | Dashboard PDF export |
| `reports/export/users/csv/` | `export_users_csv` | User roster CSV (Admin) |
| `reports/export/logs/csv/` | `export_logs_csv` | Audit/activity/login logs CSV (Admin) |
| `reports/export/<report_type>.xlsx` | `export_report_xlsx` | Per-module XLSX export |

---

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

```bash
cp .env.example .env
# Then edit .env with your values
```

See [Environment Variables](#environment-variables) for all keys.

### 5. Run migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### 6. Seed role capabilities

```bash
python manage.py seed_capabilities
```

### 7. Create a superuser

```bash
python manage.py createsuperuser
# or use the helper script:
python create_su.py
```

### 8. Run the development server

```bash
python manage.py runserver
```

Visit [http://127.0.0.1:8000](http://127.0.0.1:8000).

---

## Environment Variables

Create a `.env` file in `source-code/` (alongside `manage.py`). Template:

```env
# Django core
DJANGO_SECRET_KEY=your-secret-key-here
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost

# Database (dev: SQLite, prod: PostgreSQL)
DATABASE_URL=sqlite:///db.sqlite3
# DATABASE_URL=postgres://user:password@localhost:5432/evms

# Paystack (required for online payments)
PAYSTACK_SECRET_KEY=sk_test_...
PAYSTACK_PUBLIC_KEY=pk_test_...
PAYSTACK_BASE_URL=https://api.paystack.co

# Email — console backend for development
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
DEFAULT_FROM_EMAIL=no-reply@lasu.edu.ng

# Mailgun (production email via django-anymail)
MAILGUN_API_KEY=...
MAILGUN_SENDER_DOMAIN=mg.lasu.edu.ng
```

> ⚠️ **Never commit your `.env` file.** It is excluded via `.gitignore`.

---

## Development Commands

```bash
# Apply migrations
python manage.py makemigrations
python manage.py migrate

# Seed all role capabilities to the database
python manage.py seed_capabilities

# Create superuser
python manage.py createsuperuser

# Start development server
python manage.py runserver

# Collect static files (production)
python manage.py collectstatic --noinput

# Run Django system checks
python manage.py check

# Run Django tests
python manage.py test

# Run standalone test scripts
python test_auth.py
python test_dashboard.py
```

---

## Business Logic Rules

1. **Booking block** — Users with unpaid / non-forgiven `DamageReport` or `Penalty` records are blocked from submitting new reservations (`can_submit_booking()` + model `clean()`).
2. **Conflict detection (3 layers)** — A reservation is rejected if it overlaps with:
   - Another active `Reservation` on the same hall/date
   - A `HallBlock` date range
   - An active `InternalReservation` on the same hall/date
   - Cancelled, rejected, and closed records do not block.
3. **Pricing & VAT** — `PaymentAuthorization` computes `vat_amount` and `total_amount` from hall price, security deposit, extra charges, penalty, discounts, and VAT rate.
4. **Coupon decisions** — Ventures can approve, reject, replace, or remove a coupon request; every action is logged in `CouponActionLog` with actor and timestamp.
5. **Payment deadline** — Ventures sets a deadline (24h/48h/72h/custom); the booking moves to `PAYMENT_EXPIRED` if the applicant does not submit proof before expiry. Deadline changes are recorded in `DeadlineExtensionLog`.
6. **Strict Approval Sequence (Bursary → Ventures → Applicant)** — Applicant uploads `PaymentProof` or pays online; The Bursary MUST confirm the payments first (verifies or rejects). Upon verification (`PAYMENT_VERIFIED`), the booking advances to `AWAITING_FINAL_APPROVAL`. Ventures will then be able to do Final Approval. After Ventures grants Final Approval (`BOOKING_APPROVED`), the Applicant will then be able to download the final documents (Booking Permit).
7. **Audit trail** — `BookingTimeline` receives an entry for every significant action. `BookingStatusHistory` records every status transition. `AuditLog` records system-wide actions via `core.services.create_audit_log`.
8. **Role-based access** — Every workflow dashboard and action endpoint checks role/capability before processing. `ADMIN` always passes all capability checks. `BURSARY` is gated by `can_manage_bursary()`. Report views use `get_role_scope()` to restrict data visibility to the user's scope.
9. **Inspection reminders** — System tracks up to 3 automatic reminder notifications to Facility via `InspectionReminder` to prevent duplicate sends.
10. **Document visibility** — Documents marked `visible_to=FACILITY` are blocked by design; only `APPLICANT`, `VENTURES`, and `BURSARY` are valid targets for document sharing.
11. **Report scoping** — Each report module checks the user's scope (`full`, `ventures`, `facility`, `bursary`) and only exposes data and filter categories permitted for that scope. Admin (`full` scope) has access to all 14 report modules; other roles see a restricted subset.

---

## Deployment Notes

- Set `DJANGO_DEBUG=False` in production.
- Use PostgreSQL (`DATABASE_URL=postgres://...`) for concurrent workloads.
- Configure `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` to match your domain.
- Enable HTTPS (Let's Encrypt / Certbot).
- Serve via **Gunicorn** or **Daphne** behind **Nginx**.
- Set `SESSION_COOKIE_SECURE=True` and `CSRF_COOKIE_SECURE=True`.
- Configure a cloud media storage backend (e.g., AWS S3) for `MEDIA_ROOT`.
- Store secrets in environment variables or a secrets manager — never commit `.env`.

```bash
# Example Gunicorn launch
gunicorn hms_prj.wsgi:application --bind 0.0.0.0:8000 --workers 3
```

---

## License

This project was developed for **Lagos State University (LASU)** as an academic final-year project.  
© 2026 Ajibade Alli Akinkunmi — All rights reserved.
