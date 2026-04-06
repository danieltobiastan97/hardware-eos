# Changelog

All notable changes between branches are documented in this file.

---

## [v1.3] — 2026-04-06

> New components for natural language database queries and multi-turn conversation management.

### Added

- **ChatSession context management** — New `chat.py` module implementing `ChatSession` class for managing multi-turn conversations with automatic token tracking and context preservation.
  - Automatic token counting and limit enforcement
  - Session isolation to prevent state pollution
  - Graceful blocking when token limit reached
  - Full conversation history accessible via `get_history()`
  - 9 comprehensive unit tests in `test_chat_session.py` validating isolation, token tracking, and overflow handling

- **Ollama local model integration** — Standalone inference engine for database queries without external API dependencies.
  - Runs on `localhost:11434` (Docker-compatible)
  - Model: `gemma4:e2b` (configurable via `OLLAMA_MODEL` environment variable)
  - Temperature optimized to 0.3 for accurate, deterministic answers
  - Sampling parameters: `top_p=0.9, top_k=40, num_ctx=4096`

- **RAG (Retrieval-Augmented Generation) architecture** — New `dbchat.py` module providing natural language database queries.
  - `retrieve_relevant_products()` — intelligent filtering based on keyword detection (hardware/software/dates/recency)
  - `query_ollama()` — sends context + question to local model for answer generation
  - `process_database_query()` — orchestrates retrieval and answering pipeline
  - `interactive_chat()` — interactive CLI for testing and querying
  - Commands: `exit`, `quit`, `models`, `schema`, `all`

- **Database models** — Three SQLAlchemy ORM models in `models.py`:
  - `ProductEOS` — main product table with hardware/software type, EOS date, and ESU availability
  - `SupportTier` — multi-tier support lifecycle tracking (Standard, ESU, Premier, etc.)
  - `assetCache` — caches pipeline results with confidence scores and source links

- **Database initialization** — `db_init.py` creates tables and optional sample data.

- **Test suites for new components**:
  - `test_chat_session.py` — 9 tests for ChatSession (isolation, token tracking, context preservation)
  - `test_ollama_setup.py` — validates Ollama connectivity and model availability
  - `test_db_integration.py` — tests SQLAlchemy ORM and database queries
  - `test_improved_ollama.py` — validates temperature and prompt optimization
  - `test_rag_mode.py` — integration tests for RAG retrieval + LLM answering

- **Data folder** — `./data/asset_cache.db` for persistent SQLite storage (replaces in-memory caching pattern).

- **Environment variables**:
  - `OLLAMA_API_BASE` — Ollama endpoint (default: `http://localhost:11434`)
  - `OLLAMA_MODEL` — Model name (default: `gemma4:e2b`)
  - `DATABASE_URL` — SQLite path (default: `sqlite:///./data/asset_cache.db`)

### Changed

- **README.md** — Updated to document all three subsystems (web pipeline, RAG mode, ChatSession), new tech stack, and component overview.

- **Tech stack** — Updated Python from 3.12 to 3.13; added SQLAlchemy, SQLite, Ollama.

- **Project structure** — Added `chat.py`, `dbchat.py`, `models.py`, `db_init.py`, `data/`, and 5 new test files.

### Fixed

- Database model field definitions to cleanly support ProductEOS, SupportTier, and assetCache schemas.

---

## [v1.2] — 2026-03-27

> Changes present in `v1.2` that are **not** in `main`.

### Added

- **Network Time Protocol (NTP) support** — Product creation timestamps are now sourced from an NTP server (`pool.ntp.org`) instead of local system time, ensuring accurate UTC timestamps. Falls back to local time if NTP is unavailable.
- **UTC+8 timezone helper** — New `get_current_time_utc8()` function and `/get-time` API endpoint return the current NTP-synced time in UTC+8.
- **`ntplib==0.4.0`** added to `requirements.txt`.
- **Database diagnostic scripts** — Two new utility scripts for inspecting the SQLite database:
  - `check_db.py` — lists all tables and record counts using the raw `sqlite3` module.
  - `verify_db.py` — verifies database connectivity and record counts via SQLAlchemy.
- **`chatbot` class scaffold** in `classes.py` — initial skeleton for a future chatbot feature (persistent chat with LLM history support).
- **Enhanced CSV export** — The `/export-csv` endpoint now falls back to querying the database when the in-memory results cache is empty, allowing historical data to be exported across sessions.
- **Shift-click range selection for rows** — Row selection in the asset tables now supports shift-click to select or deselect a contiguous range of rows.

### Fixed

- **Database initialisation path** — Database file path changed from the relative `sqlite:///asset_cache.db` to the persistent container path `sqlite:////app/data/asset_cache.db`, preventing data loss between container restarts.
- **Default Excel sheet name** — `Helper.preprocess()` now defaults to `sheet='Asset List'` instead of `sheet='Sheet1'` to match the expected spreadsheet format.
- **Checkbox / row-selection bug** — Reworked `syncSelection()` (previously `resetSelection()`) to preserve existing selections when the table is reloaded, instead of unconditionally resetting all checkboxes. Added `lastToggledRow` tracking and `applyRowSelection()` / `applyRangeSelection()` helpers to make range selection reliable.
- **NTP timestamp stored on product creation** — `ProductEOSRepo.add_product()` now accepts an optional `created_timestamp` parameter; both the pipeline and the item-refresh endpoint pass the NTP-synced time when persisting products.

### Changed

- **Removed optional database fallback** — Database initialisation no longer wraps in a `try/except`; the app now requires a working database connection on startup (the persistent path is always available inside the container).
- **Removed redundant cache helpers** — `check_cache()` and `save_to_cache()` functions removed from `webpage.py`; caching logic is handled directly by `ProductEOSRepo`.
- **`parse_date` import removed** from `webpage.py` (it is used internally by `models.py` only).

---

## [main / v1.1] — 2026-03-26

> Changes present in `main` that are **not** in `v1.2` (merged via PR #1 from `beta/v1.1`).

### Added

- **Docker support** — `Dockerfile`, `compose.yaml`, and `.dockerignore` added for containerised deployment.
- **SQLAlchemy database cache** — `models.py` introduces `ProductEOS`, `SupportTier`, and `assetCache` ORM models. `db_init.py` handles schema creation.
- **Session authentication** — Login/logout routes and `login.html` template added; all main routes protected by `@login_required`.
- **SQLAlchemy-backed result caching** — Pipeline results are persisted to SQLite and served from cache on repeat runs, reducing redundant API calls.
- **Cache refresh endpoint** — `/refresh-item` allows individual assets to be re-queried and updated in the database.
- **`README.md`** — Comprehensive project documentation covering features, quickstart, file format, usage, and security notes.
- **`DATABASE.md`** — Documentation for the database schema and cache behaviour.
- **`identified_bugs.txt`** — Developer notes tracking known issues.
- **Test suite** — `database_test.py` and `test_cache_integration.py` added for database model and cache integration testing.
- **Inline name editing** — Asset names in the table can be edited before triggering the pipeline.
- **Individual asset search** — Allows searching for a single asset without running the full pipeline.

### Changed

- **Major UI overhaul** — `file-inspector.html` significantly expanded with new controls, styling, and features (row selection, expandable detail rows, cache status indicators, streaming progress).
- **`requirements.txt`** converted from a binary/lock format to a minimal plain-text format with pinned versions.
- **`prompt.py`** and `classes.py` updated to support the new pipeline and caching architecture.
