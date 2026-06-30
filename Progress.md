# EVMS — Event Hall Management System (LASU)
## Project Progress & Status Report

---

## 1. Project Overview

**System Name:** Event Hall Management System (EVMS)
**Institution:** Lagos State University (LASU)
**Developer:** Ajibade Alli Akinkunmi (Matric: 220591056)
**Supervisor:** Prof. Aribisala Benjamin Segun
**Department:** Computer Science, Faculty of Computing and Information Technology
**Submission Target:** July 2026

**Original Scope (per project-doc.docx):**
- Web-based hall booking for students, staff, departments, and external users
- Real-time availability checking with conflict detection
- Centralized database for users, halls, events, bookings, and audit trails
- Automated approval workflow
- Email/web notifications
- Analytical reports (usage frequency, peak hours, departmental activity)
- Audit trail for transparency and accountability

**Explicitly Excluded from Original Scope:**
- Payment processing (implemented in codebase)
- Physical hall maintenance
- External (non-LASU) commercial event hosting
- Facility security monitoring
- RFID integration

---

## 2. Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 6.0.4 |
| Database | SQLite (development) |
| Payments | Paystack (paystack / django-anymail) |
| Admin UI | Jazzmin (Django admin theme) |
| Rich Text | django-ckeditor-5 |
| PDF Reports | reportlab |
| Excel Export | openpyxl |
| Auth | Custom AbstractUser with role-based access |
| Deployment | Standard Django WSGI (django-jazzmin settings configured) |

---

## 3. Application Modules (Architecture)

```
source-code/
├── hms_prj/                  # Project config (settings.py, urls.py, wsgi.py)
├── core/                     # Shared utilities, audit logs, FAQs, announcements, contact
├── users/                    # Custom user model, auth, profile management
├── hall/                     # Hall catalog, facilities, bookmarks, home/public pages
├── reservations/             # Booking engine, conflict detection, coupons, penalties
├── payments/                 # Paystack integration, invoices, payment lifecycle
├── notifications/            # In-app notifications + email broadcasts
└── reports/                  # Admin reports dashboard, CSV/PDF/Excel exports
```

---

## 4. Data Model Summary

### Users (`users.User`)
- Custom `AbstractUser` with email uniqueness
- Roles: `ADMIN`, `STAFF`, `STUDENT`, `EXTERNAL`, `VENTURES`, `FACILITY`
- Fields: `phone_number`, `department`, `profile_image`, `is_verified`, `is_blocked`
- Auto-assigns `STUDENT` role for `@lasu.edu.ng` emails
- **New:** `RoleCapability` model for database-driven RBAC
- **New:** `LoginLog` model with IP address and user agent tracking
- **New:** `users/services.py` with `can(user, capability)` and `record_login()`

### Hall (`hall.Hall`)
- Types: `LECTURE_HALL`, `EXAM_HALL`, `SEMINAR_ROOM`, `EVENT_HALL`, `CONFERENCE_HALL`
- Fields: `faculty`, `building`, `capacity`, `price_per_hour`, `description`, `image`
- **New:** `owner_department` (VENTURES or FACILITY)
- **New:** `rules` and `terms` text fields
- Related: `HallImage` (gallery), `Facility` (through `HallFacility`), `HallBookmark`
- **New:** `HallBlock` model for blocking specific date ranges (maintenance/special events)

### Reservations (`reservations.Reservation`)
- **New:** 13-status workflow: `SUBMITTED`, `FORWARDED`, `UNDER_REVIEW`, `REJECTED`, `AVAILABLE`, `APPROVED_PAYMENT`, `PAYMENT_PENDING`, `PAID`, `CONFIRMED`, `COMPLETED`, `INSPECTION_PENDING`, `DAMAGE_REPORTED`, `CLOSED`, plus backward-compatible `PENDING` and `APPROVED` aliases
- Purpose: 10 categories (Lecture/Academic, Examination, Social/Cultural, Meeting/Conference, Workshop/Training, Graduation/Convocation, Religious Programme, Sports/Recreation, Exhibition/Fair, Other)
- Duration billing: `MINUTE`, `HOUR`, `DAY` (pro-rated)
- Auto-generated reference: `LASU-YYYYMMDD-HHMMSS`
- **New:** `notes` field for applicant notes
- Coupon support (percentage or fixed discount)
- Overlap/conflict prevention via `clean()`
- Blocks users with unpaid damages/penalties
- **New:** `BookingStatusHistory` — immutable audit trail of every status change
- **New:** `BookingLog` — actor, action, details, timestamp
- **New:** `ReservationMessage` — internal/external messaging thread
- **New:** `ReservationDocument` — versioned document uploads (Authorization Letter, Permit, Image, Other)
- **New:** `HallInspection` — post-event inspection with PASSED/FAILED/DAMAGE_REPORTED results
- **New:** `WorkflowService` class enforcing state guards, atomic transitions, history/log creation, and notifications

### Payments (`payments.Payment`)
- Provider: `PAYSTACK` only
- Methods: `CARD`, `TRANSFER`
- **New:** `record_manual_payment` view for Ventures administrators (cash/bank transfer)
- Linked to `Reservation`, `DamageReport`, or `Penalty`
- Server-side verification callback, signed success/failure tokens
- Updated to handle both legacy `PENDING` and new `PAYMENT_PENDING` statuses
- Auto-advances to `PAID` on successful verification

### Other Models
- `core.AuditLog` — action tracking (`user`, `model_name`, `action`, `timestamp`)
- `core.Announcement` — rich-text announcements with optional image/video
- `core.FAQ` — active/inactive questions
- `core.ContactMessage` — contact form with admin reply + email notification
- **New:** Custom error handlers (`403.html`, `404.html`, `500.html`) in `core/views.py`
- `notifications.Notification` / `BroadcastMessage` — per-user notifications and role-targeted broadcasts
- **New:** Signals for `ReservationMessage`, `ReservationDocument`, and `HallInspection` auto-notifications
- `reservations.DamageReport` / `Penalty` — incident tracking with payment linkage
- `reservations.Coupon` — enhanced with per-user limits, validity ranges, minimum booking amounts, maximum discount caps, and role/hall/faculty/department restrictions

---

## 5. Implementation Status

### 5.1 Completed Modules

| Module | Status | Notes |
|--------|--------|-------|
| **Users & Auth** | ✅ Complete | Expanded to 6 roles, RoleCapability RBAC, LoginLog, record_login() integrated |
| **Hall Catalog** | ✅ Complete | owner_department, rules/terms, HallBlock date blocking API, admin updated |
| **Reservation Engine** | ✅ Complete | 13-status workflow enums, 5 new models, WorkflowService with state guards |
| **Coupon Engine** | ✅ Complete | Enhanced with per-user limits, min amounts, max caps, role/hall/faculty restrictions |
| **Payments** | ✅ Complete | Backward-compatible with new PAYMENT_PENDING status; manual payment recording added |
| **Notifications** | ✅ Complete | Auto-notifications on messages, document uploads, inspections |
| **Core / Admin** | ✅ Complete | AuditLog, Announcements, FAQ, ContactMessage; custom 403/404/500 error pages |
| **Reports** | ✅ Complete | Revenue breakdown by booking/penalty/damage fees added to dashboard |
| **Admin Panel (Jazzmin)** | ✅ Complete | All new models registered; LASU branding intact |
| **Navigation** | ✅ Complete | Ventures desk and Facility desk links added for relevant roles |
| **Templates** | ✅ Complete | Ventures, Facility, and Admin dashboard templates; error page templates; rules/terms on hall detail |
| **Tests** | ✅ Complete | Unit tests for WorkflowService, Coupon, HallBlock, User registration, RoleCapability |

### 5.2 Partially Complete / Needs Attention

| Area | Issue | Priority |
|------|-------|----------|
| **Migrations** | New models and fields must be applied via `makemigrations` + `migrate`. Cannot be auto-run due to environment tooling limitation. | **User must run manually** |
| **README** | `README.md` written at `source-code/README.md` | ✅ Done |

### 5.3 Out of Scope (Verified Not Implemented)

- RFID / physical hall monitoring
- SMS notifications (email-only via console or Mailgun-backed Anymail)
- Multi-tenant / subdomain support
- Calendar sync (Google/Outlook)
- REST/GraphQL API layer (views are server-rendered Django views)
- Docker / containerization configs
- Native mobile application

---

## 6. Key Business Logic Rules (Enforced in Code)

1. **Blocking logic:** Users with unpaid `DamageReport` or `Penalty` cannot create new reservations (`reservations/models.py:92-93`).
2. **Conflict detection:** Same hall + same date + overlapping time = rejected (`reservations/models.py:102-106`). Cancelled, rejected, and closed bookings do not block.
3. **Pricing model:** Hourly rate (`price_per_hour`) billed per duration type (minute/hour/day). Facilities snapshot their price at booking time via `ReservationFacility.price_at_booking_time`.
4. **Coupon validity:** Active, not expired, usage limit not reached, per-user limit, minimum booking amount, maximum discount cap, and role/hall/faculty/department eligibility enforced via `is_valid_for_user()`.
5. **Payment finalization:** Successful Paystack verification auto-advances reservation to `PAID` for both legacy `PENDING` and new `PAYMENT_PENDING` statuses. Marks damages/penalties as paid, sends notification + email.
6. **Audit trail:** Key actions logged via `core.services.create_audit_log`. Every workflow transition writes `BookingStatusHistory` and `BookingLog`.
7. **Role-based access:** `ADMIN` / `STAFF` can view all reservations, payments, reports. `VENTURES` has its own workflow dashboard. `FACILITY` has its own dashboard. `STUDENT` / `EXTERNAL` see only their own.
8. **Workflow state guards:** `WorkflowService` enforces valid transitions and prevents unauthorized status jumps.

---

## 7. Known Technical Debt

1. **SQLite in production config** — Settings are set for SQLite; production migration to PostgreSQL is not yet addressed.
2. **Static/media storage** — Local filesystem; no S3/CDN configuration.
3. **Email backend** — Defaults to console email backend; Mailgun key optional.
4. **Migrations not applied** — New schema changes (`RoleCapability`, `LoginLog`, `HallBlock`, `BookingStatusHistory`, `BookingLog`, `ReservationMessage`, `ReservationDocument`, `HallInspection`, enhanced `Coupon`) must be applied with `makemigrations` + `migrate`.
5. **No Docker / docker-compose** — No containerized deployment path documented.

---

## 8. Next Steps / Immediate Actions Required

1. **Run migrations:** `cd source-code && python manage.py makemigrations && python manage.py migrate`
2. **Configure production email** (Mailgun/SendGrid) and store keys securely via environment variables.
3. **Decide on PostgreSQL** for production and document the migration path.
4. **Add CI/CD** (GitHub Actions or similar) to run lint + tests on push.
5. **Document deployment** — Gunicorn, Nginx, HTTPS config.
6. **Expand test coverage** — add payment gateway mocking tests, UI integration tests.

---

## 9. Rules & Standards (from Agent.md)

- **Correctness, simplicity, maintainability, performance** are priorities.
- **Code quality:** Clean, readable, modular; avoid duplication (DRY).
- **Security:** No hardcoded secrets, environment variables for keys, input validation, prevent XSS/SQLi.
- **Before changes:** Read existing files, respect current architecture, do not rewrite unnecessarily.
- **File handling:** Update existing files instead of duplicating; keep structure organized.
- **Testing:** Write testable code, add error handling, log meaningful debug info.
- **Documentation:** Comments only where necessary; keep README updated for major changes.

---

## 10. Summary

The EVMS codebase has been fully expanded to align with the documented 13-status workflow, 6-role RBAC, and complete feature set described in `project-doc.docx`. Core additions include:

- **User Management:** 6 roles with database-driven `RoleCapability` system and `LoginLog` security tracking.
- **Hall Management:** Ownership fields, usage rules/terms, and date-range blocking via `HallBlock`.
- **Reservation System:** Complete 13-status workflow with `WorkflowService` enforcing state guards, immutable history/log entries, and automated notifications.
- **Document Management:** Versioned uploads per reservation with type-safe validation.
- **Post-Event Inspection:** Pass/fail/damage reporting with automatic staff notification.
- **Communication:** In-app notifications and email broadcasts for status changes, booking messages, document uploads, and inspection results.
- **Reporting:** Revenue breakdown by booking fees, penalty payments, and damage fees.
- **Payments:** Backward-compatible with existing flows, plus manual payment recording for Ventures staff.
- **Error Handling:** Custom 403, 404, and 500 pages.
- **Tests:** Automated tests covering WorkflowService transitions, coupon restrictions, HallBlock validation, and user registration/login.

The main remaining action is **applying the database migrations** (`makemigrations` / `migrate`), which must be run manually before the new models and fields are available in the database.

### 11. Role-Specific Dashboards (Chapter 3 Compliance)

All six user levels defined in Chapter 3 now have dedicated frontend dashboards with role-appropriate capabilities:

| Role | Dashboard | Capabilities |
|------|-----------|--------------|
| **Student** | `hall/dashboard.html` | View own bookings, book halls, pay online, view notifications |
| **External** | `hall/dashboard.html` | Same as Student (non-LASU applicants) |
| **Staff** | `hall/staff_dashboard.html` | Own bookings + access to Reports, Ventures desk, Facility desk |
| **Department** | `hall/department_dashboard.html` | Department-level bookings, reports access |
| **Ventures Unit** | `reservations/ventures_dashboard.html` | Forward, review, mark available, approve payment, confirm, complete, cancel bookings |
| **Facility Unit** | `reservations/facility_dashboard.html` | Confirm availability, reject, open inspection, report damage, close bookings |
| **System Admin** | `reservations/admin_dashboard.html` | Full system overview, user management, all bookings, access to Django Admin |

**Access Control Enforcement:**
- `hall/dashboard` now redirects users to their role-specific dashboard automatically
- Staff and Department dashboards enforce `403 Forbidden` for unauthorized roles
- Ventures and Facility dashboards include workflow action buttons with server-side state validation via `WorkflowService`
- Navigation (`base.html`) dynamically shows only relevant dashboard links per role
