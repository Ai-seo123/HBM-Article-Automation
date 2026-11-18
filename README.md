# HBM Article Automation Platform

An end-to-end automated publishing pipeline for Home Business Magazine articles. The platform ingests client instructions and DOCX attachments from Basecamp 3, generates SEO-optimized articles using Google Gemini AI, audits them against a 28-point QA engine and real Yoast SEO scoring, sources licensed images via Envato Market, and securely drafts posts into WordPress.

---

## Architecture Overview

The system is designed with a three-tier modular architecture:

1. **Frontend (`frontend/`)**: Modern React 19 + Vite dashboard with responsive Tailwind-styled components, Employee Authentication, Wizard Workflow, Admin Activity Tracking, and Reports.
2. **Backend (`backend/`)**: High-performance FastAPI service orchestrating Basecamp OAuth 2.0, Google Gemini AI generation, DOCX parsing, 28-point QA engine, Envato image search, and WordPress REST API multi-site synchronization.
3. **Yoast SEO Sidecar (`yoast-sidecar/`)**: Dedicated Node.js Express microservice running Yoast's official `yoastseo` package for pre-publishing readability and focus-keyphrase scoring.

```
                           +--------------------------+
                           |  React + Vite Frontend   |
                           |   (Port 5173 / Render)   |
                           +------------+-------------+
                                        |  REST / CORS
                                        v
                           +--------------------------+
                           |     FastAPI Backend      |
                           |   (Port 8000 / Render)   |
                           +----+--------+--------+---+
                                |        |        |
        +-----------------------+        |        +-----------------------+
        v                                v                                v
+---------------+               +-----------------+              +-----------------+
|  Basecamp 3   |               |   Yoast SEO     |              |   Google Gemini |
|  OAuth 2.0    |               |  Node.js Sidecar|              |   1.5 Flash AI  |
+---------------+               |   (Port 3939)   |              +-----------------+
                                +-----------------+
                                         |
        +--------------------------------+--------------------------------+
        v                                                                 v
+-------------------------------+                               +-------------------+
|  Envato Market / PhotoDune    |                               | WordPress REST API|
|  Image Search API             |                               | (Draft-Only Mode) |
+-------------------------------+                               +-------------------+
```

---

## Core Security & Policy Safeguards

- **Destination Restriction**: All test WordPress publishing is restricted to approved staging/test destinations (e.g. `https://espialsolutions.com`).
- **Production Hard-Block**: Direct writing to `https://homebusinessmag.com` is permanently blocked in code.
- **Draft-Only Enforcement**: WordPress REST calls enforce `status="draft"`; publishing directly to live status is disabled.
- **Multi-Tenant Token Encryption**: Basecamp OAuth tokens and credentials are encrypted per-employee using Fernet symmetric encryption.
- **CSRF & Session Security**: HTTP-only cookies, SameSite enforcement, and CSRF token verification protect all mutating endpoints.

---

## Directory Structure

```
hbm-article-automation/
├── backend/                  # FastAPI Application
│   ├── api/routes/           # API endpoints (auth, basecamp, wizard, qa, reports, etc.)
│   ├── core/                 # Config, database, security, date utilities
│   ├── models/               # SQLAlchemy ORM models (employee, article, report, site)
│   ├── schemas/              # Pydantic validation models
│   ├── services/             # Core logic (article processor, QA engine, Gemini, Yoast)
│   ├── storage/              # Wizard sessions and backup storage (.gitkeep)
│   ├── tests/                # 11 regression test suites (136 tests)
│   ├── requirements.txt      # Python dependencies
│   ├── .env.example          # Backend configuration template
│   └── main.py               # Application entrypoint
├── frontend/                 # React + Vite Application
│   ├── src/                  # Components, pages, context, layouts, router
│   ├── package.json          # Frontend dependencies
│   └── .env.example          # Frontend configuration template
├── yoast-sidecar/            # Yoast Node.js Sidecar Service
│   ├── server.js             # Express server executing yoastseo
│   ├── package.json          # Node dependencies (express, yoastseo)
│   ├── README.md             # Sidecar documentation
│   └── .env.example          # Sidecar environment template
└── .gitignore                # Root Git exclusion rules
```

---

## Quick Start (Local Development)

### 1. Prerequisites
- Python 3.11+ (tested on Python 3.12 / 3.13)
- Node.js >= 18.0.0
- npm or pnpm

### 2. Backend Setup
```bash
cd backend
python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# Fill in your credentials in .env
uvicorn main:app --reload --port 8000
```

### 3. Yoast Sidecar Setup
```bash
cd yoast-sidecar
npm install
cp .env.example .env
# Set BCWP_SECRET to match backend .env
npm start
```

### 4. Frontend Setup
```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

---

## Running Automated Tests

Run the full regression test suite (11 test files, 136 tests):

```bash
cd backend
python -m unittest discover -s tests -p "test_*.py"
```

Frontend production build verification:

```bash
cd frontend
npm run build
```

---

## License & Proprietary Notice

Confidential and proprietary. Internal tool developed for Home Business Magazine article automation by Espial Solutions.
