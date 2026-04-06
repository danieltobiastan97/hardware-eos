# Asset Intelligence Tracker

A comprehensive asset lifecycle management system combining **Google Gemini AI** with real-time search, local **Ollama** inference with RAG (Retrieval-Augmented Generation), and context-aware conversation management. Features include:
- Web application for bulk EOS/EOL lookups via Gemini with Google Search grounding
- Natural language database queries via local Ollama model (no external API calls)
- Multi-turn conversation support with automatic token tracking and context management

Upload a spreadsheet, select rows, trigger the AI pipeline, and get structured EOS data with confidence scores and source URLs — all streamed live to your browser. Or query your cached product database conversationally in plain English.

---

## Development Status

| Component | Status | Access |
|---|---|---|
| Web Pipeline (Gemini AI) | ✓ Production | Web UI (`http://localhost:8080`) |
| Database Models (SQLAlchemy) | ✓ Production | Integrated with web pipeline |
| Ollama RAG Mode | 🔨 In Development | Terminal: `python dbchat.py` |
| ChatSession Context | 🔨 In Development | Python import + terminal tests |

---

### Web Interface (Gemini AI Pipeline)
- **Bulk file upload** — accepts `.csv` and `.xlsx` files with `Hardware` and `Software` columns
- **Manual search** — type any product names (semicolon-separated) without uploading a file
- **Concurrent AI pipeline** — processes multiple assets in parallel via Google Gemini with Google Search grounding
- **Live streaming results** — results appear row-by-row via Server-Sent Events as the AI finishes each item
- **Result caching** — already-processed items are served from memory on repeat runs, skipping unnecessary API calls
- **Expandable detail rows** — click any row to see EOS date, support tiers, confidence breakdown, summary, and source URLs
- **CSV export** — export all pipeline results to a timestamped CSV file
- **Inline name editing** — edit asset names in the table before running the pipeline
- **Row selection** — cherry-pick which rows to process
- **Session authentication** — simple username/password login protecting all routes

### Database & RAG (Ollama Local Model) — **IN DEVELOPMENT**
> Ollama components are currently in active development and integration with the web frontend. Terminal-only access available on development server.

- **Natural language queries** — ask questions about products without SQL knowledge
- **Local inference** — Ollama model runs locally on `localhost:11434` (no external API dependencies)
- **Smart filtering** — automatically detects intent (hardware/software/dates) and retrieves relevant data
- **Context-aware answers** — LLM responds based only on database context, never making up data
- **Efficient retrieval** — max 10 products per query to optimize token usage

### Multi-Turn Conversations (ChatSession) — **IN DEVELOPMENT**
> ChatSession is currently in active development and integration with the web frontend. Terminal-only access available on development server.

- **Context preservation** — maintain conversation state across multiple turns with automatic history tracking
- **Token management** — automatic counting and limit enforcement to prevent blocking
- **Session isolation** — independent sessions prevent state pollution between conversations
- **Graceful overflow handling** — blocks new messages when token limit reached instead of truncating context

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13, Flask 3.1, Gunicorn |
| AI (Web) | Google Gemini (`gemini-3-flash-preview`) via `google-genai` |
| AI (Local) | Ollama (`gemma4:e2b`) for RAG-based database queries |
| ORM & Database | SQLAlchemy, SQLite (`./data/asset_cache.db`) |
| Data Processing | pandas, openpyxl, numpy |
| Frontend | Vanilla JS, custom CSS (dark theme, DM Mono font) |
| Streaming | Server-Sent Events (SSE) |
| Container | Docker + Docker Compose |

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- A **Google Gemini API key** — get one at [Google AI Studio](https://aistudio.google.com/)

---

## Quickstart

### 1. Clone the repository

```bash
git clone https://github.com/danieltobiastan97/hardware-eos.git
cd hardware-eos
```

### 2. Configure secrets

Create a `.env` file in the project root (never commit this):

```env
APP_SECRET_KEY=your-random-secret-key
APP_ADMIN_PASSWORD=your-login-password
```

Create `keys.json` for the Gemini API key (also never commit this):

```json
{
  "GEMINI_API_KEY": "your-gemini-api-key-here"
}
```

> `keys.json` is mounted into the container as read-only at runtime. Add it to `.gitignore`.

### 3. Build and run

```bash
docker-compose up --build
```

The app will be available at **http://localhost:8080**

To run in detached mode:

```bash
docker-compose up --build -d
```

### 4. Log in

Default credentials (override via `.env`):
- **Username:** `admin`
- **Password:** `Generate your own password`

---

## Input File Format

Upload a `.csv` or `.xlsx` file with the following columns:

| Hardware | Software |
|---|---|
| Dell PowerEdge R720 | Windows Server 2016 |
| Cisco Catalyst 2960 | Adobe Acrobat DC |
| HP ProLiant DL380 | |

- Columns must be named exactly `Hardware` and `Software`
- Either column can be empty or omitted
- Duplicate entries are automatically removed during preprocessing

---

## Quick Test with Sample Data

Try the app immediately with the included **`test.csv`** file:
1. From the web UI, upload `test.csv` (included in the project root)
2. It contains 3 hardware items and 2 software items ready for testing
3. Click **Trigger AI Intelligence Pipeline** to see live results

This is useful for testing the full workflow before uploading your own asset data.

---

## Usage

1. **Upload a file** — drag & drop or click to browse, or switch to manual search mode
2. **Review the asset tables** — hardware and software rows appear after preprocessing
3. **Select rows** — all rows are selected by default; uncheck any you want to skip
4. **Edit names** — hover a row and click the pencil icon to adjust an asset name before processing
5. **Trigger the pipeline** — click **Trigger AI Intelligence Pipeline**; results stream in live
6. **Expand rows** — click any completed row for the full detail view
7. **Export** — use the **Export** button to download all results as a `.csv`

---

## Project Structure

```
hardware-eos/
├── webpage.py               # Flask app — routes, SSE pipeline, CSV export
├── prompt.py                # Gemini client setup and async AI call logic
├── classes.py               # Helper, Cleaner, Processing utility classes
├── models.py                # SQLAlchemy ORM models (ProductEOS, SupportTier, assetCache)
├── chat.py                  # ChatSession — multi-turn conversation context management
├── dbchat.py                # Ollama + RAG interface for natural language database queries
├── db_init.py               # Database schema initialization script
├── prompt.txt               # System prompt / instructions sent to Gemini
├── keys.json                # API keys (mount at runtime, do not commit)
├── requirements.txt         # Python dependencies
├── Dockerfile
├── compose.yaml
├── data/                    # SQLite database and asset cache
│   └── asset_cache.db       # Database file with product and support tier data
├── templates/
│   ├── file-inspector.html  # Main single-page UI
│   └── login.html           # Login page
├── static/                  # Static assets (CSS, fonts, images)
├── test_chat_session.py     # ChatSession unit tests (9 tests)
├── test_ollama_setup.py     # Ollama connectivity validation
├── test_db_integration.py   # Database integration tests
├── test_improved_ollama.py  # Temperature and prompt optimization tests
└── test_rag_mode.py         # RAG retrieval + LLM answer integration tests
```

---

## Configuration

### Web Application & Gemini

All configuration is passed via environment variables:

| Variable | Default | Description |
|---|---|---|
| `APP_SECRET_KEY` | `change-this-secret-key` | Flask session signing key |
| `APP_ADMIN_PASSWORD` | `changeme` | Login password for the `admin` user |
| `APP_ADMIN_PASSWORD_HASH` | *(unset)* | Optional: Werkzeug password hash (overrides plaintext password) |

The Gemini API key is read from `keys.json`, which is volume-mounted into the container.

### Ollama & Database (RAG Mode) — *IN DEVELOPMENT*

> These components are actively being developed and integrated with the web frontend. Currently accessible via terminal on development server.

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_API_BASE` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `gemma4:e2b` | Model to use for database queries |
| `DATABASE_URL` | `sqlite:///./data/asset_cache.db` | SQLite database path |

#### Setup Requirements (Development)
1. Ensure Ollama is running locally on `localhost:11434`
2. Pull the `gemma4:e2b` model (or configure `OLLAMA_MODEL` for a different model)
3. Initialize database with `db_init.py` before running RAG queries
4. **Terminal Access:** Run `python dbchat.py` in the development server to interact with RAG mode

### ChatSession (Multi-Turn Conversations) — *IN DEVELOPMENT*

> Currently in active development and integration. Terminal-only access available on development server.

The `ChatSession` class handles conversation state automatically. Initialize with:

```python
from chat import ChatSession

session = ChatSession(
    model="gemini-1.5-flash",  # Model name
    api_key="your-api-key"     # API key
)

# Send a message
response = session.send_message("What hardware expires in 2026?")
print(response)

# Access history and token usage
print(session.get_history())
print(f"Tokens used: {session.token_usage}")
```

**Features:**
- ✓ Automatic token counting and tracking
- ✓ Context preservation across multiple turns
- ✓ Session isolation (no global state pollution)
- ✓ Graceful blocking when token limit reached
- ✓ Full conversation history accessible

---

## How It Works

### Web Pipeline (Gemini + Search)
1. User uploads CSV/XLSX or manually enters product names
2. Flask preprocesses and deduplicates entries
3. Concurrent pipeline queries Gemini (with Google Search grounding) for each product
4. Results stream back via SSE as each product completes
5. Extended Support Unit (ESU) availability is noted
6. All results cached to SQLite for future queries

### RAG Mode (Ollama + Local DB) — *IN DEVELOPMENT*
1. User asks a natural language question about products (via terminal: `python dbchat.py`)
2. `retrieve_relevant_products()` analyzes keywords and filters database intelligently
3. Max 10 products formatted as readable context
4. Context + question sent to local Ollama model
5. Ollama generates natural language answer based solely on provided data
6. No SQL exposed to user; no external API calls

> **Access:** Currently available only via terminal on development server. Web frontend integration in progress.

### ChatSession (Multi-Turn) — *IN DEVELOPMENT*
1. Create a `ChatSession` instance with model + API key
2. Send messages via `send_message()`
3. Conversation history maintained automatically
4. Token counting prevents hitting model limits
5. Each session isolated from others

> **Access:** Currently available only via terminal on development server. Web frontend integration in progress.

---

## Development

Code changes to `webpage.py`, `classes.py`, `prompt.py`, `prompt.txt`, and `templates/` are volume-mounted — no rebuild is needed. Simply restart the container:

```bash
docker-compose restart
```

A full rebuild is only needed when `requirements.txt` or the `Dockerfile` itself changes:

```bash
docker-compose up --build
```

### Running Tests

Test suites are available for all components:

```bash
# ChatSession context management (9 tests) — IN DEVELOPMENT
python test_chat_session.py

# Ollama connectivity — IN DEVELOPMENT
python test_ollama_setup.py

# Database integration
python test_db_integration.py

# RAG retrieval + LLM answering — IN DEVELOPMENT
python test_rag_mode.py

# Optimization validation — IN DEVELOPMENT
python test_improved_ollama.py
```

### Testing Development Features

**To test Ollama RAG mode interactively:**
```bash
python dbchat.py
# Then ask questions at the prompt (e.g., "Show me all software products")
# Commands: exit, quit, models, schema, all
```

**To test ChatSession programmatically:**
```python
from chat import ChatSession
session = ChatSession(model="gemini-1.5-flash", api_key="your-key")
response = session.send_message("What hardware expires in 2026?")
print(response)
```

---

## Security Notes

- `keys.json` **must not be committed to version control** — add it to `.gitignore`
- Set a strong `APP_SECRET_KEY` and `APP_ADMIN_PASSWORD` in production via `.env`
- For hashed passwords, generate with `werkzeug.security.generate_password_hash` and set `APP_ADMIN_PASSWORD_HASH`
- The app runs as a single Gunicorn worker (required for in-memory result caching to work correctly across requests)
- Ollama instance should be isolated to trusted networks (no authentication by default)

---

## License

MIT
