# Changelog

All notable changes between branches are documented in this file.

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
