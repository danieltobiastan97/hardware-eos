# Hardware EOS Tracker

An intelligent asset lifecycle management system powered by **Google Gemini AI** for End-of-Support (EOS) date discovery and tracking. Combines bulk AI-powered lookups, conversational database queries, and real-time EOS status indicators.

**Key Features:**
- 🤖 **Ask AI Chat** — Conversational queries about asset EOS/EOL dates with RAG database retrieval
- 📊 **Bulk Pipeline** — Upload spreadsheets, auto-lookup EOS dates via Gemini API with live streaming results
- 📅 **EOS Status Indicators** — Real-time date validation showing expired assets with red warning badges
- 💾 **Smart Caching** — Results cached to SQLite; re-run avoids unnecessary API calls
- 🔍 **Preview & Confirm** — Retrigger API calls show before/after comparison before saving
- 📤 **Selective Export** — Export only checked rows as CSV

---

## Features

### Web Interface (Primary)

#### 1. Asset Pipeline
- **Bulk upload** — Accepts `.csv` and `.xlsx` files with `Hardware` and `Software` columns
- **Manual entry** — Type asset names directly without uploading files
- **Concurrent processing** — Multiple assets queried in parallel via Google Gemini with web search grounding
- **Live streaming** — Results appear row-by-row via Server-Sent Events as processing completes
- **Result caching** — Already-processed assets served from database/memory, skipping redundant API calls
- **Expandable details** — Click any row to see full EOS date, support tiers, confidence, sources, and summary
- **Selective export** — Check/uncheck rows and export only selected assets to CSV
- **Inline editing** — Edit asset names before triggering the pipeline
- **Inline refresh** — Retrigger API for a single asset, preview changes, then confirm save

#### 2. Ask AI Chat (Beta)
- **Conversational interface** — Ask natural language questions about EOS/EOL dates
- **RAG retrieval** — Automatically fetches relevant product context from local database before answering
- **Multi-turn awareness** — Maintains conversation context across multiple messages in the same session
- **Session persistence** — Chat history saved to disk; reload on page refresh
- **Token tracking** — Monitors Gemini API usage; warns at 80%, blocks at 1000 token limit per conversation
- **Response grounding** — Fallback logic prevents model from claiming data is missing when assets are actually present in database
- **Clear chat** — Start fresh conversation with one click

#### 3. EOS Status Indicators
- **NTP time sync** — Checks dates against authoritative NTP servers (falls back to local time if unavailable)
- **Real-time validation** — Displays red "EOS" badge next to any asset with passed end-of-support date
- **Applied everywhere** — Works in pipeline results, cached data, manual refreshes, and export payloads
- **Visual clarity** — Red outlined box with red text for easy identification

#### 4. Security & Access Control
- **Session authentication** — Username/password login protecting all routes
- **Configurable credentials** — Override defaults via environment variables
- **Password hashing** — Optional Werkzeug password hashing for production deployments

---

## Tech Stack

| Component | Technology |
|---|---|
| **Backend** | Python 3.12, Flask 3.1 |
| **AI & LLM** | Google Gemini 2.5 Flash (`google-genai`), Web Search grounding |
| **Database** | SQLAlchemy ORM, SQLite (`./data/asset_cache.db`) |
| **Time Sync** | NTP via `ntplib` for accurate EOS date validation |
| **Data Processing** | pandas, openpyxl for spreadsheet parsing |
| **Frontend** | Vanilla JavaScript, modern CSS (dark theme, DM Mono font) |
| **Streaming** | Server-Sent Events (SSE) for live pipeline results |
| **Container** | Docker + Docker Compose |
| **Web Server** | Gunicorn (single-worker for in-memory caching) |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13, Flask 3.1, Gunicorn |
| AI (Web & Chat) | Google Gemini (`gemini-2.5-flash`) via `google-genai` SDK |
| ORM & Database | SQLAlchemy, SQLite (`./data/asset_cache.db`) |
| Data Processing | pandas, openpyxl, numpy |
| Frontend | Vanilla JS, custom CSS (dark theme, DM Mono font) |
| Streaming | Server-Sent Events (SSE) |
| Container | Docker + Docker Compose |

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- A **Google Gemini API key** — get one free at [Google AI Studio](https://aistudio.google.com/)

---

## Quickstart

### 1. Clone the Repository

```bash
git clone https://github.com/danieltobiastan97/hardware-eos.git
cd hardware-eos/hardware-eos
```

### 2. Create Configuration Files

**.env** (project root, never commit):
```env
APP_SECRET_KEY=your-random-secret-key-here
APP_ADMIN_PASSWORD=your-login-password
```

**keys.json** (project root, never commit):
```json
{
  "GEMINI_API_KEY": "your-gemini-api-key-from-aistudio"
}
```

> Add both files to `.gitignore` to prevent accidental commits.

### 3. Build and Run

```bash
docker compose up --build -d
```

The app will be available at **http://localhost:3000**

### 4. Log In

- **Username:** `admin` (from `.env`)
- **Password:** Your configured password (from `.env`)

---

## Input File Format

Upload a `.csv` or `.xlsx` file with these columns:

| Hardware | Software |
|---|---|
| Dell PowerEdge R750 | Windows Server 2022 |
| Cisco Catalyst 3650 | Adobe Acrobat 2024 |

**Requirements:**
- Column headers must be exactly `Hardware` and `Software`
- Either column can be left empty
- Duplicates are automatically removed during preprocessing

---

## Usage Workflow

1. **Upload or Enter** — Drag a file into the upload area, or switch to "Manual Search" to type asset names
2. **Review & Prepare** — Preprocessed rows appear in separate hardware/software tables
3. **Select Assets** — All rows are selected by default; uncheck any you want to skip
4. **Edit Names** — Click the pencil icon on any row to adjust the name before processing
5. **Trigger Pipeline** — Click "Trigger AI Intelligence Pipeline"; results stream live
6. **Expand Rows** — Click any completed row to see full details (EOS, tiers, confidence, sources, summary)
7. **Retrigger Assets** — Click the refresh icon on any row to query the API again; preview changes in the modal before saving
8. **Export Results** — Select rows and click "Export CSV"—only checked assets are included
9. **Ask AI** — Click the "Ask AI" button to start a conversation about your assets

---

## Ask AI (Chat)

### How It Works

1. **Open Chat** — Click the "Ask AI (Beta)" button in the toolbar
2. **Ask a Question** — Type any natural language question about EOS/EOL dates
3. **RAG Retrieval** — System automatically fetches relevant products from your database
4. **AI Response** — Gemini answers based on the retrieved context + your question
5. **Multi-Turn** — Ask follow-up questions; chat remembers the conversation within the session
6. **Token Tracking** — See current token usage and limits at the top of the chat

### Example Queries

- *"What is the end of support for Adobe Photoshop 2022?"*
- *"Which hardware products expire in 2026?"*
- *"Show me all software with no end date information"*
- *"When does Windows Server 2019 reach end of support?"*

### Chat Limits

- **1000 tokens per conversation** — Conversations auto-close when limit is reached
- **800 token warning** — Appears at 80% usage
- **Clear chat** — Start a fresh conversation with the "Clear" button

---

## Retrigger & Preview

Single-asset refresh without full pipeline re-run:

1. **Click Refresh Icon** — Appears on any completed row
2. **Preview Changes** — Modal shows before/after comparison side-by-side
3. **Review Differences** — Verify new data before saving
4. **Accept & Save** — PATCH endpoint persists selected changes to database
5. **Row Updates** — Table updates in place with new values and EOS status

---

## Export

### All Results
- Exports entire processed dataset as CSV
- Includes all columns: Name, Type, EOS Date, Confidence, Summary, Support Tiers

### Selected Rows Only
- Check only the rows you want to export
- Click "Export CSV"
- Only selected assets included in the file

### EOS Date Formatting
- Actual dates displayed as ISO format (YYYY-MM-DD)
- Placeholder dates humanized as "No EOS found"
- Expired dates marked with 🔴 red "EOS" indicator (when viewed in web UI)

---

## Project Structure

```
hardware-eos/
├── webpage.py                      # Flask routes, SSE pipeline, export, caching
├── unified_chat.py                 # Ask AI chat backend with RAG + Gemini
├── models.py                       # SQLAlchemy ORM (ProductEOS, SupportTier)
├── classes.py                      # Helper utilities for data processing
├── prompt.py                       # Gemini client setup and API logic
├── templates/
│   ├── file-inspector.html         # Main UI (pipeline, chat modal, export)
│   └── login.html                  # Login page
├── static/css/
│   └── styles.css                  # Dark theme, layout, responsive design
├── prompts/
│   ├── guardrail.txt               # Gemini system prompt (database restrictions)
│   ├── db_guardrail.txt            # Ask AI safety rules
│   └── prompt.txt                  # Asset lookup instructions
├── data/
│   └── asset_cache.db              # SQLite database (auto-created)
├── chat_sessions/                  # Persistent chat history (auto-created)
├── tests/
│   └── test_fixes.py               # Regression tests (8 tests, pytest)
├── requirements.txt                # Python dependencies
├── compose.yaml                    # Docker Compose configuration
├── Dockerfile                      # Container image definition
├── CHANGELOG.md                    # Feature history
└── README.md                       # This file
```

---

## Configuration

### Web Application

Environment variables (set in `.env`):

| Variable | Default | Purpose |
|---|---|---|
| `APP_SECRET_KEY` | `change-this-secret-key` | Flask session encryption key |
| `APP_ADMIN_PASSWORD` | `changeme` | Login password for `admin` user |
| `APP_ADMIN_PASSWORD_HASH` | *(unset)* | Optional: Use hashed password instead of plaintext |

### Gemini API

Set in `keys.json`:
```json
{
  "GEMINI_API_KEY": "your-key-here"
}
```

### Database

Automatically created at `./data/asset_cache.db` on first run.

---

## Development

### Local Changes (No Rebuild Needed)

Changes to `webpage.py`, `unified_chat.py`, `templates/`, `static/css/`, or `prompts/` are live-updated. Restart the container:

```bash
docker compose restart
```

### Rebuild (When Dependencies Change)

Rebuild when `requirements.txt` or `Dockerfile` is modified:

```bash
docker compose up --build -d
```

### View Logs

```bash
docker compose logs -f web
```

---

## Testing

Run regression tests locally:

```bash
# Activate venv
source .venv/bin/activate  # or your venv path

# Run pytest
pytest tests/test_fixes.py -v
```

**Tests Cover:**
- Retrigger preview/confirm save flow
- Selected-row export functionality
- EOS expiration date checking
- Classification validation
- Chat retrieval consistency
- Response grounding fallback

---

## Troubleshooting

### App Won't Start
```bash
# Check logs
docker compose logs web

# Rebuild from scratch
docker compose down
docker compose up --build -d
```

### Chat Not Finding Assets
- Ensure assets are imported to database (run pipeline at least once)
- Verify database file exists at `/app/data/asset_cache.db`
- Check Gemini API key is valid and has quota

### EOS Status Not Showing
- Verify NTP time is accessible (app logs will show "Warning: NTP request failed" if not)
- Clear browser cache: Some cached responses may not have the `is_eos_passed` flag
- Retrigger individual assets to refresh timestamps

### Export Not Working
- Ensure at least one row is checked
- Check browser console for errors (F12)
- Verify CSV filename doesn't conflict with OS restrictions

---

## Security Notes

- ⚠️ Never commit `keys.json` or `.env` — add to `.gitignore`
- 🔐 Set a strong `APP_SECRET_KEY` and `APP_ADMIN_PASSWORD` in production
- 🛡️ For production, use `APP_ADMIN_PASSWORD_HASH` with `werkzeug.security.generate_password_hash()`
- 🚨 Gemini API key has billing implications — monitor usage at [Google Cloud Console](https://console.cloud.google.com/)

---

## Deployment

### Docker

Production-ready Docker setup included. Customize:

1. Set environment variables in `.env`
2. Mount `keys.json` securely
3. Configure reverse proxy (nginx/Caddy)
4. Enable HTTPS
5. Use strong passwords and session keys

### Example Nginx Reverse Proxy

```nginx
server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## Roadmap

- ✅ Ask AI chat with RAG retrieval
- ✅ Retrigger preview + confirmation
- ✅ Selected-row export
- ✅ EOS status indicators with NTP time sync
- ✅ Chat retrieval grounding
- ⏳ Bulk import from vendor APIs
- ⏳ Support tier lifecycle tracking
- ⏳ Alert notifications (Slack, email)
- ⏳ Advanced analytics dashboard

---

## License

MIT

---

## Support

For issues, questions, or feature requests, visit [GitHub Issues](https://github.com/danieltobiastan97/hardware-eos/issues).
