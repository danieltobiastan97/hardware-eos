# Changelog

All notable changes between branches are documented in this file.

---

## [v1.3] — 2026-04-08

> Gemini-powered Ask AI feature with multi-turn conversation management, database guardrails, EOS status indicators, and comprehensive prompt injection prevention.
> **Status:** Production-ready with Beta label. Enhanced security hardening.

### Added

- **Prompt Injection Prevention System** — Multi-layered defense across backend, frontend, and data pipeline
  - **Server-side chat validation** `is_suspicious_chat_input()` in `classes.py` detects 20+ injection patterns
  - **Client-side validation** `detectPromptInjection()` in `app.js` blocks injections before server round-trip
  - **Pattern detection** for context override, roleplay jailbreaks, credential requests, formatting attacks
  - **Length & newline limits** prevent padding/encoding bypass attempts
  - Suspicious inputs logged and blocked with user-friendly security warnings
  - **Production impact:** Integrates seamlessly with existing RAG and vague query protections

- **Input Sanitization & Response Validation**
  - `sanitize_asset_name()` escapes XML/HTML special characters (`<`, `>`, `&`, `"`, `'`)
  - `validate_eos_response()` enforces EOS response schema before persistence
  - Confidence scores validated as float 0.0-1.0 range
  - Support Model and Hardware/Software enums strictly enforced
  - Response schema mismatch triggers retry or fallback to template

- **Interactive CLI Test Interface** — `prompt.py` main() replaced with interactive session
  - Accepts semicolon-separated asset names: `Dell PowerEdge R750; Windows Server 2019`
  - Real-time processing with automatic retry (up to 3 attempts for failed items)
  - Formatted result display with EOS date, confidence, support model, and source URLs
  - Exit commands: `exit`, `quit`, `q` with keyboard interrupt support (Ctrl+C)
  - Perfect for testing prompt injection patterns against Gemini backend

- **Chat Security Enhancements**
  - HTML escaping in chat bubbles (`escapeHtml()` utility)
  - Token limit enforcement (1000 tokens) with 429 status on limit reached
  - Warning threshold at 80% (800 tokens) in chat UI
  - Injection-blocked messages shown in-chat with security explanation
  - Unauthenticated chat access properly rejected with 401

### Ask AI Chat Feature
- Modal popup with Gemini logo button in file inspector toolbar
- Natural language queries about EOS/EOL dates for IT assets
- Uses Gemini's native web search capability for real-time information
- **[PRODUCTION - Beta Status]**

- **GeminiChatSession context management** — `GeminiChatSession` class in `unified_chat.py` for reliable conversation handling
  - Multi-turn conversation history with automatic persistence
  - JSON-based session storage in `./chat_sessions/` directory
  - Per-user session isolation with automatic session IDs
  - Token tracking and limit enforcement (1000 token limit with 800 token warning)
  - Graceful handling when token limits reached
  - Full conversation history accessible and loadable across requests

- **RAG (Retrieval-Augmented Generation) architecture** — Intelligent database filtering to provide relevant context to Gemini
  - `retrieve_relevant_products()` function filters database based on user query keywords
  - Detects hardware/software/vendor-specific queries and retrieves only relevant products
  - Prevents vague queries from returning entire database
  - SQL query optimization for fast asset lookups
  - Session freshness enforcement with rollback/expire_all to prevent stale reads

- **Database guardrail enforcement** — SQL queries restricted to product information for security
  - `guardrail.txt` prompt file enforces database access patterns
  - Prevents unauthorized data retrieval or injection attacks
  - Guardrails loaded and prepended to Gemini system instruction
  - Fallback error handling if guardrail file is missing

- **Ask AI response grounding fix** — Deterministic fallback when model claims data missing
  - Auto-detects false "not in database" responses when DB context has results
  - Replaces misgrounded responses with data synthesized directly from retrieved products
  - Prevents user confusion when assets exist but model claims otherwise

- **EOS Status Indicator** — Real-time End-of-Support date status display
  - NTP-based date checking against current UTC time
  - Red outlined badge ("EOS") appears next to expired dates
  - Applied to all asset rows during pipeline processing and manual refresh
  - Visible in both initial load and dynamic result updates

- **Markdown response rendering** — marked.js library for formatted chat responses
  - GitHub Flavored Markdown support
  - Tables, code blocks, lists, and emphasis preserved from AI responses
  - Syntax highlighting ready for code blocks
  - CSS styling for professional appearance

- **Chat UI enhancements**
  - "(Beta)" label in modal header and button tooltip
  - Clear chat history button with confirmation dialog
  - Close modal button with keyboard shortcut (Escape)
  - Responsive modal sizing with overflow handling
  - Word-break handling for long table cells and code blocks
  - Table overflow CSS with max-width constraints and font sizing optimization

### Fixed

- **Retrigger save flow** — Two-phase preview + confirmation pattern
  - POST retrigger API call returns preview without persisting to database
  - Shows old vs new result comparison in expandable modal
  - PATCH endpoint for explicit user-confirmed save only
  - Prevents accidental overwrites and data loss

- **Export selected rows only** — CSV export respects checkbox selection
  - POST endpoint filters to selected asset IDs only
  - Previously exported entire dataset regardless of selection
  - Error handling for empty or missing IDs

- **Ask AI database retrieval consistency** — Multiple hardening layers
  - Session refresh before each database query (rollback + expire_all)
  - Enforced grounding in Gemini prompt when context has results
  - Auto-fallback to deterministic response if model fails to ground
  - Proper context_used flag for consistent metadata reporting

- **Classification strict enforcement** — Non-Hardware/Software assets blocked from persistence
  - Pipeline now validates explicit "Hardware" or "Software" classification
  - Rejects anything ambiguous or unclassified
  - Updated test coverage to verify rejection behavior

- **Placeholder EOS date humanization** — User-friendly display of unknown dates
  - Internal `2099-12-31` placeholder shown as "No EOS found" in UI and exports
  - Applied across all response payloads, cache returns, and API endpoints
  - Prevents confusing year-2099 dates visible to end users

### Technical Details

- **Backend**: Flask 3.1 with Gunicorn + Python 3.12
- **AI Model**: Google Gemini 2.5 Flash with Web Search tool
- **Database**: SQLAlchemy ORM with SQLite storage (`./data/asset_cache.db`)
- **Session Storage**: JSON files with 30-minute inactivity timeout for auto-expiry
- **NTP Integration**: ntplib for accurate time syncing (falls back to local time on failure)
- **API Key Integration**: Keys loaded from `keys.json` with secure handling
- **Dependencies**: google-genai==1.68.0, flask==3.1.0, sqlalchemy-based ORM, ntplib
- **Testing**: pytest with in-memory SQLite, mocked external AI calls, 8 regression tests
