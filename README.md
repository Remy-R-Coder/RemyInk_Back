# RemyInk Technical Architecture & Functional Design

## Overview

**RemyInk** is a curated freelance marketplace for academic services. The platform emphasizes:

- A strict cap of **20 vetted freelancers**.
- **Auto-generated accounts** for clients and freelancers.
- **Admin-controlled operations** (no public job postings).
- **Stripe** for client payments; **M-Pesa B2C** for freelancer payouts.
- Automated dispute handling and submission validation.

---

## 1. Functional Specification

### 1.1 User Roles

- **Admin**  
  Full system control: manages users, disputes, payments, moderation.

- **Freelancer**  
  Vetted experts (`Remy01`–`Remy20`), manually onboarded, linked to fixed subject areas.

- **Client**  
  No manual signup. System auto-generates credentials (`Client001`, etc.) on first inquiry.

---

### 1.2 User Onboarding

#### Freelancer

- Only 20 slots available.
- Must select:
  - **1 Primary Category** (e.g., Law, Nursing)
  - **Up to 3 Subject Areas** (e.g., Criminology, Intellectual Property)
- Selections are **immutable post-onboarding**.
- Assigned fixed IDs (`Remy01` to `Remy20`).

#### Client

- First inquiry triggers account creation (`Client001`, `Client002`, ...).
- Credentials sent via email/SMS.
- Subsequent visits use **session-based auto-login**.

---

### 1.3 Service Discovery (No Job Posting)

> Clients do **not** post jobs publicly.

- Clients select:
  - **Category** → **Subject Area**
- System lists freelancers tagged accordingly.
- Clients can:
  - View freelancer profiles
  - Initiate chat
  - Agree on scope
  - Pay via Stripe (triggers order creation)

---

### 1.4 Order Lifecycle

1. Chat → Agreement → **Client pays via Stripe**
2. **Order Status**: In Progress
3. Freelancer uploads:
   - `assignment.pdf`
   - `plag_report.pdf`
   - `ai_report.pdf`
4. Client marks order as complete
5. **7-day dispute window** opens
6. If no dispute, **funds auto-released to freelancer**

---

### 1.5 Dispute Handling

- Disputes can be opened within 7 days post-submission.
- Admin reviews:
  - Chat logs
  - Uploaded files
  - Dispute reason
- Admin actions:
  - Full refund
  - Partial refund
  - Release funds to freelancer

---

### 1.6 Payments & Fees

- Platform takes a **20% fee**:
  - 10% from client
  - 10% from freelancer
- Payment Methods:
  - **Stripe** (client → platform)
  - **M-Pesa B2C** (platform → freelancer)
- Payouts processed:
  - **Automatically** after 7 days if no dispute
  - **Manually** by admin during dispute resolution

---

### 1.7 Inbox Moderation

- Real-time scanning for:
  - Phone numbers
  - Email addresses
  - Keywords (e.g., WhatsApp, Telegram)
- On detection:
  - Message blocked
  - Warning issued to freelancer
  - **3 warnings** = **14-day suspension**

---

## 2. System Architecture

### 2.1 Backend Stack

- **Django + DRF** – REST APIs and core logic
- **PostgreSQL** – relational DB
- **Celery + Redis** – background tasks (payouts, timers)
- **Django Channels** – WebSocket chat
- **Sentry** – error monitoring
- **Stripe** – client payments
- **M-Pesa B2C** – freelancer payouts

---

### 2.2 Frontend Stack

- **Next.js** – SSR + API consumption
- **TailwindCSS** – UI styling
- **Auth Strategy**:
  - Session-based
  - Clients: auto-login on revisit
  - Freelancers: standard login/password

---

## 3. Detailed Modules

### 3.1 User Management

- Role-based (`Admin`, `Freelancer`, `Client`)
- Auto-ID generation (`RemyXX`, `ClientXXX`)
- Tracks warnings and suspensions (freelancers)

---

### 3.2 Chat & Moderation

- Real-time messaging via **WebSockets**
- Moderation using:
  - Regex filters (live)
  - ML-based detection (future enhancement)
- All warnings are logged and linked to users
- Admin dashboard shows:
  - Warning logs
  - Blocked messages
  - Off-platform attempts

---

### 3.3 Order & Escrow System

- **Client pays via Stripe** → funds held in escrow
- **Freelancer delivers files**
- **Payout triggered**:
  - Automatically after 7 days
  - Or manually after dispute resolution

---

### 3.4 Submission Workflow

Freelancer must upload all of:

- `assignment.pdf`
- `plag_report.pdf`
- `ai_report.pdf`

→ Order cannot be marked as "submitted" until all files are present.

---

### 3.5 Dispute Resolution

- Dispute object includes:
  - Chat logs
  - Evidence files
  - Dispute reason
- Admin resolution options:
  - Full refund
  - Partial refund
  - Payout release

---

### 3.6 Payment Engine

- **Stripe Checkout** – client-facing payment gateway
- **Platform Wallet / Escrow** – tracks fund states
- **M-Pesa B2C Integration**:
  - Celery tasks queue payout jobs
  - Logs: transaction ID, response, timestamp

---

## 4. UI/UX Design

### 4.1 Theme

- **Colors**: Red, Black, White
- **Design**: Minimal, academic, professional

---

### 4.2 Homepage

- Tagline: `"0% AI, <10% Plagiarism, 100% Quality"`
- Key sections:
  - Trusted Freelancers
  - Fast Delivery
  - Quality Guarantee

---

### 4.3 Client Flow

- No signup required
- Session-based access
- Flow:
  1. Select Category → Subject Area
  2. View matched freelancers
  3. Chat → Agreement → Pay
  4. Receive work

---

### 4.4 Freelancer Dashboard

- Tabs:
  - Active Orders
  - Delivered
  - Disputed
- Other info:
  - Warning count
  - Earnings summary
  - Payout status

---

## 5. Development Milestones (8 Weeks)

### Week 1–2
- Django + DRF setup
- PostgreSQL schema
- User onboarding + ID auto-generation
- Basic chat module (WebSockets)
- Categories & Subject Areas

### Week 3–4
- Stripe integration
- Escrow wallet model
- File submission module

### Week 5–6
- Dispute module
- M-Pesa B2C integration (sandbox)
- Admin panel dashboards

### Week 7–8
- Frontend polish
- Testing (unit + integration)
- Deployment:
  - Docker
  - CI/CD (Railway / VPS / Heroku)

---

## 6. Future Enhancements

- 🤖 **AI Grader** – auto-evaluate submissions
- 🧠 **Smart Matching Engine** – recommend freelancers
- 📱 **Mobile App** – via React Native
- 💬 **Sentiment & Quality Analyzer** – detect tone + quality in chats

---

## Deployment Topology

```plaintext
Client
  ↓
Cloudflare (WAF/CDN)
  ↓
Nginx → Django ASGI (Daphne)
          ↓      ↘
        Celery → Redis
          ↓
   PostgreSQL | S3/MinIO
# r_main

            ┌────────────────────┐
            │  get_csrf_and_sess │
            │  (Guest Session)   │
            └─────────┬──────────┘
                      │
          ┌───────────▼─────────────┐
          │       User Login        │
          │  TokenObtainPairView    │
          └─────────┬──────────────┘
                    │
         ┌──────────▼───────────┐
         │     UserProfile       │
         │ UserProfileViewSetNew │
         │  AccountSettingsView  │
         └──────────┬───────────┘
                    │
       ┌────────────▼────────────┐
       │ OnboardingViewSet       │
       │ - Freelancer onboarding │
       │ - Client finalization   │
       └────────────┬────────────┘
                    │
        ┌───────────▼───────────┐
        │   DashboardSummary     │
        │  (aggregates stats)   │
        └───────────┬───────────┘
                    │
    ┌───────────────┴───────────────┐
    │                               │
┌───▼───────────────┐       ┌───────▼──────────────┐
│ DashboardStatsView │       │ DashboardJobsView    │
└───┬───────────────┘       └────────┬────────────┘
    │                               │
    │                               │
    │           ┌───────────────────▼─────────────┐
    │           │ DashboardNotificationsView      │
    │           │   combines Chat & Notification  │
    │           └─────────────────┬──────────────┘
    │                             │
    │                             │
    │                   ┌─────────▼───────────┐
    │                   │ GuestThreadsView    │
    │                   │   (Chat Threads)    │
    │                   └─────────┬───────────┘
    │                             │
    │                  ┌──────────▼─────────┐
    │                  │ ThreadUnreadCount  │
    │                  │ UnreadMessagesCount│
    │                  └──────────┬─────────┘
    │                             │
    │                       ChatMessage
    │                             │
    │                ┌────────────▼─────────────┐
    │                │      RatingViewSet       │
    │                └──────────────────────────┘
    │
    │ UserProfile children (Portfolio, Skills, WorkExperience etc.)
    │
┌───▼──────────────┐
│ PortfolioViewSet │
│ WorkExpViewSet   │
│ EducationViewSet │
│ CertificationView│
│ SkillViewSet     │
└─────────────────┘
# fin_remy_back
