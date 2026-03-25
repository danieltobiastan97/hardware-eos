# Asset Intelligence Tracker

A self-hosted web application that uses **Google Gemini AI** with real-time Google Search grounding to look up End-of-Support (EOS) and End-of-Life (EOL) dates for hardware and software assets. Upload a spreadsheet, select rows, trigger the pipeline, and get structured EOS data with confidence scores and source URLs — all streamed live to your browser.

---

## Features

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

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, Flask 3.1, Gunicorn |
| AI | Google Gemini (`gemini-3-flash-preview`) via `google-genai` |
| Data | pandas, openpyxl, numpy |
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
git clone <your-repo-url>
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
- **Password:** `changeme`

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
├── webpage.py          # Flask app — routes, SSE pipeline, CSV export
├── prompt.py           # Gemini client setup and async AI call logic
├── classes.py          # Helper, Cleaner, Processing utility classes
├── prompt.txt          # System prompt / instructions sent to Gemini
├── keys.json           # API keys (mount at runtime, do not commit)
├── requirements.txt    # Python dependencies
├── Dockerfile
├── compose.yaml
└── templates/
    ├── file-inspector.html   # Main single-page UI
    └── login.html            # Login page
```

---

## Configuration

All configuration is passed via environment variables:

| Variable | Default | Description |
|---|---|---|
| `APP_SECRET_KEY` | `change-this-secret-key` | Flask session signing key |
| `APP_ADMIN_PASSWORD` | `changeme` | Login password for the `admin` user |
| `APP_ADMIN_PASSWORD_HASH` | *(unset)* | Optional: Werkzeug password hash (overrides plaintext password) |

The Gemini API key is read from `keys.json`, which is volume-mounted into the container.

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

---

## Security Notes

- `keys.json` **must not be committed to version control** — add it to `.gitignore`
- Set a strong `APP_SECRET_KEY` and `APP_ADMIN_PASSWORD` in production via `.env`
- For hashed passwords, generate with `werkzeug.security.generate_password_hash` and set `APP_ADMIN_PASSWORD_HASH`
- The app runs as a single Gunicorn worker (required for in-memory result caching to work correctly across requests)

---

## License

MIT
