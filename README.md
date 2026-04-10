# Hardware EOS Tracker

An intelligent asset lifecycle management system powered by **Google Gemini AI** for End-of-Support (EOS) date discovery and tracking. Upload a spreadsheet, trigger the AI pipeline, and get structured EOS data streamed live to your browser. Query your database conversationally using Ask AI, and see real-time EOS status badges for any assets that have passed their end-of-support date.

---

## Features

- **Bulk AI Pipeline** — Upload `.csv` or `.xlsx` files; assets are queried via Google Gemini with Google Search grounding and results stream live via SSE
- **Ask AI Chat** — Conversational natural language queries grounded in your local database with multi-turn awareness and token tracking
- **EOS Status Indicators** — Red "EOS" badge on any asset whose end-of-support date has already passed, validated against NTP time
- **Result Caching** — Processed results saved to SQLite; repeated runs skip redundant API calls
- **Retrigger & Preview** — Re-query a single asset and preview before/after changes before saving
- **Selective Export** — Check the rows you want, then export only those to CSV
- **System Tagging** — Create named systems (projects/applications), tag assets with one or more systems, and bulk-assign across selected rows
- **System Overview** — Dedicated dashboard at `/system-overview` listing all systems with asset counts and quick-filter by system
- **Session Authentication** — Username/password login protecting all routes

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, Flask 3.1, Gunicorn |
| AI Pipe | Google Gemini (`gemini-3-flash-preview`) with Google Grounding (Search Intelligence) |
| AI Chat/RAG | Google Gemini (`gemini-2.5-flash`) via `google-genai` |
| Database / ORM | SQLAlchemy, SQLite (`./data/asset_cache.db`) |
| Data Processing | pandas, openpyxl, numpy |
| Time Validation | ntplib (NTP time sync with local fallback) |
| Frontend | Vanilla JS, custom CSS (dark theme, DM Mono font) |
| Streaming | Server-Sent Events (SSE) |
| Container | Docker, Docker Compose |

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- A **Google Gemini API key** — get one free at [Google AI Studio](https://aistudio.google.com/)

---

## Setup

### 1. Clone the Repository

```bash
git clone https://github.com/danieltobiastan97/hardware-eos.git
cd hardware-eos/hardware-eos
```

### 2. Create `keys.json`

Create `keys.json` in the project root with your Gemini API key:

```json
{
  "GEMINI_API_KEY": "your-gemini-api-key-here"
}
```

> **Never commit this file.** Add `keys.json` to `.gitignore`.

### 3. Create `.env`

Create a `.env` file in the same directory:

```env
APP_SECRET_KEY=your-random-secret-key
APP_ADMIN_PASSWORD=your-login-password
```

> Use a long random string for `APP_SECRET_KEY` (e.g. generate with `python -c "import secrets; print(secrets.token_hex(32))"`).

### 4. Build and Run

```bash
docker compose up --build -d
```

The app will be available at **http://localhost:3000**

### 5. Log In

- **Username:** `admin`
- **Password:** The value you set for `APP_ADMIN_PASSWORD` in `.env`

---

## Input File Format

Upload a `.csv` or `.xlsx` file with these column headers:

| Hardware | Software |
|---|---|
| Dell PowerEdge R750 | Windows Server 2022 |
| Cisco Catalyst 3650 | Adobe Acrobat 2024 |
| HP ProLiant DL380 | |

- Headers must be exactly `Hardware` and `Software`
- Either column can be left empty
- Duplicates are automatically removed during preprocessing

---

## Usage

1. **Upload or Enter** — Drag a file into the upload area, or switch to **Manual Search** to type asset names
2. **Review Tables** — Preprocessed assets appear in separate hardware and software tables
3. **Select Rows** — All rows are selected by default; uncheck any you want to skip
4. **Edit Names** — Click the pencil icon on any row to adjust the name before processing
5. **Trigger Pipeline** — Click **Trigger AI Intelligence Pipeline**; results stream in live
6. **Expand Rows** — Click any completed row to see EOS date, support tiers, confidence, sources, and summary
7. **Retrigger** — Click the refresh icon on a row to re-query; preview changes in the modal before saving
8. **Export** — Select rows and click **Export CSV** — only checked rows are included

---

## Ask AI

1. Click **Ask AI (Beta)** in the toolbar
2. Ask any natural language question about your assets (e.g. *"Which hardware expires in 2026?"*)
3. The system retrieves relevant products from your database and passes them as context to Gemini
4. Follow-up questions maintain conversation context within the same session
5. Token usage and limits are shown at the top of the chat panel; the conversation closes at 1000 tokens

---

## System Tagging

Systems are named groups (e.g. "Project Alpha", "HR Platform") that let you organise assets by project or application.

1. Click **Manage Systems** in the file inspector toolbar to create, rename, or delete systems
2. After processing, each asset row shows a **Systems** column — click the tag icon to assign systems to that asset
3. To bulk-assign, select multiple rows and click **Bulk Assign System**
4. Navigate to **System Overview** (link in the toolbar) to see all systems and their assets in one place

---

## System Overview

The `/system-overview` page provides a high-level dashboard of all your systems:

- Lists every system with its total asset count
- Click a system card to filter and view only the assets tagged to it
- Manage systems (create/rename/delete) without leaving the overview
- Uses the same Ask AI chat panel available in the file inspector

---

## EOS Status Indicators

Any asset whose end-of-support date has already passed is marked with a red outlined **EOS** badge in the date column. Dates are validated against time fetched from NTP servers (`pool.ntp.org`), falling back to local system time if NTP is unavailable.

---

## Project Structure

```
hardware-eos/
├── webpage.py                  # Flask routes, SSE pipeline, export, caching, system API
├── unified_chat.py             # Ask AI chat backend (RAG + Gemini)
├── models.py                   # SQLAlchemy ORM models (ProductEOS, SupportTier, System, ProductSystem)
├── classes.py                  # Helper utilities for data processing
├── prompt.py                   # Gemini client setup and API logic
├── templates/
│   ├── file-inspector.html     # Main single-page UI (with system tagging)
│   ├── system-overview.html    # System Overview dashboard
│   └── login.html              # Login page
├── static/css/
│   └── styles.css              # Dark theme, layout
├── prompts/
│   ├── guardrail.txt           # Pipeline system prompt
│   ├── db_guardrail.txt        # Ask AI safety rules
│   └── prompt.txt              # Asset lookup instructions
├── data/
│   └── asset_cache.db          # SQLite database (auto-created on first run)
├── chat_sessions/              # Persisted chat history (auto-created)
├── keys.json                   # Gemini API key (mount at runtime, do not commit)
├── requirements.txt
├── compose.yaml
├── Dockerfile
└── CHANGELOG.md
```

---

## Configuration

Environment variables (set in `.env`, loaded by Docker Compose):

| Variable | Default | Purpose |
|---|---|---|
| `APP_SECRET_KEY` | `change-this-secret-key` | Flask session signing key |
| `APP_ADMIN_PASSWORD` | `changeme` | Login password for the `admin` user |
| `APP_ADMIN_PASSWORD_HASH` | *(unset)* | Optional Werkzeug password hash — overrides plaintext password |
| `NTP_SERVER` | `pool.ntp.org` | NTP host used for EOS date validation |
| `NTP_ENABLED` | `1` | Set to `0`, `false`, or `no` to skip NTP and use local UTC time |
| `NTP_CACHE_TTL_SECONDS` | `300` | How long (in seconds) to reuse a cached NTP result |
| `NTP_WARN_INTERVAL_SECONDS` | `900` | Minimum seconds between repeated NTP-failure log warnings |

The Gemini API key is read exclusively from `keys.json`, which is volume-mounted read-only into the container.

---

## Development

Changes to `webpage.py`, `unified_chat.py`, `classes.py`, `prompt.py`, `templates/`, `static/`, and `prompts/` are volume-mounted and take effect after a container restart — no rebuild needed:

```bash
docker compose restart
```

Rebuild only when `requirements.txt` or `Dockerfile` changes:

```bash
docker compose up --build -d
```

View live logs:

```bash
docker compose logs -f web
```

---

## Security Notes

- Never commit `keys.json` or `.env` — add both to `.gitignore`
- Set a strong, unique `APP_SECRET_KEY` in production
- For production deployments, prefer `APP_ADMIN_PASSWORD_HASH` over a plaintext password
- Monitor Gemini API usage at [Google Cloud Console](https://console.cloud.google.com/) — key has billing implications
- The app intentionally runs as a single Gunicorn worker to keep in-memory SSE result caching consistent across requests

---

## License

MIT
