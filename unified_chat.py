"""
Gemini Chat Interface with RAG
Combines RAG database retrieval with Google Gemini backend
"""

import json
import re
import requests
import warnings
import os
import asyncio
import time
from typing import Optional, Dict, List
from datetime import datetime, date
from sqlalchemy import create_engine, text, or_, func
from sqlalchemy.orm import sessionmaker
from pathlib import Path

# Get absolute path to script directory for file paths
SCRIPT_DIR = Path(__file__).resolve().parent

# Suppress warnings
warnings.filterwarnings("ignore", message=".*thought_signature.*")

# Import database models
from models import ProductEOS, SupportTier, assetCache, Base
from prompt import keys_and_prompt_setup, client_setup, Spinner, chat_client_setup

# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

# Database Configuration
# Build database path using absolute directory
DB_DIR = SCRIPT_DIR / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = str(DB_DIR / "asset_cache.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Gemini Configuration
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_CONTEXT_WINDOW = 1_000_000
GEMINI_SAFETY_THRESHOLD = 0.85

# Database globals
db_engine = None
db_session = None
db_schema = None

# Chat history storage - use absolute path
CHAT_HISTORY_DIR = str(SCRIPT_DIR / "chat_sessions")
Path(CHAT_HISTORY_DIR).mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════════════════════
# Database Functions
# ═══════════════════════════════════════════════════════════════════════════

def init_database() -> bool:
    """Initialize database connection and cache schema."""
    global db_engine, db_session, db_schema
    
    print("📊 Initializing database connection...", end=" ")
    try:
        db_engine = create_engine(DATABASE_URL, echo=False)
        
        with db_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        Session = sessionmaker(bind=db_engine)
        db_session = Session()
        
        db_schema = get_database_schema()
        
        print("✓")
        print(f"   Database: {DB_PATH}")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False


def get_database_schema() -> str:
    """Get database schema information for context."""
    return """
DATABASE SCHEMA:

Table: product_eos
- id (Integer, Primary Key)
- name (String, 255 chars, Unique)
- summary (String) - Text description
- hardware_software (String) - 'Hardware' or 'Software'
- support_model (String) - e.g., 'Version-Based'
- eos_date (Date) - End of Support Date
- source_urls (JSON) - Array of source URLs
- confidence (Float) - Confidence score (0-1)
- created_date (DateTime)
- updated_date (DateTime)

Table: support_tier (related to product_eos via product_id)
- id (Integer, Primary Key)
- product_id (Integer, Foreign Key)
- tier (String) - Name of support tier
- end_date (Date) - End date for this tier
- created_date (DateTime)
"""


def is_vague_query(user_query: str) -> bool:
    """
    Check if a query is too vague and lacks specific asset references.
    Returns True if the query appears to be asking for bulk database content.
    """
    query_lower = user_query.lower()

    # If user includes version/year markers, treat as specific.
    if any(ch.isdigit() for ch in user_query):
        return False

    # If query contains at least two meaningful non-generic tokens,
    # it's likely targeting a specific asset (e.g. "adobe photoshop").
    generic_terms = {
        'asset', 'assets', 'product', 'products', 'item', 'items',
        'hardware', 'software', 'date', 'dates', 'eos', 'eol',
        'lifecycle', 'summary', 'table', 'overview', 'list', 'all'
    }
    _STOP = {
        'for', 'the', 'and', 'what', 'when', 'does', 'is', 'are',
        'will', 'has', 'have', 'end', 'of', 'support', 'about',
        'can', 'you', 'tell', 'me', 'show', 'give', 'please'
    }
    tokens = [t for t in query_lower.replace('/', ' ').replace('-', ' ').split() if len(t) > 2 and t not in _STOP]
    specific_tokens = [t for t in tokens if t not in generic_terms]
    if len(specific_tokens) >= 2:
        return False
    
    # Vague triggers: asking for "all", "everything", "list", "dump", "summary", "table", etc.
    vague_triggers = [
        'what are the', 'show me', 'list all', 'list the', 'give me',
        'all the', 'every', 'what do you have', 'how many', 'count',
        'enumerate', 'dump', 'important dates', 'all dates', 'all eos',
        'all products', 'all assets', 'all items', 'all hardware',
        'all software', 'everything', 'summary', 'table', 'overview',
        'list of', 'create a table', 'create a summary', 'show table',
        'create table', 'asset lifecycle', 'lifecycle summary', 'eos summary'
    ]
    
    for trigger in vague_triggers:
        if trigger in query_lower:
            return True
    
    return False


def retrieve_relevant_products(user_query: str, limit: int = 10, session_override=None) -> str:
    """Retrieve relevant products from database based on user query keywords."""
    _session = session_override or db_session
    if not _session:
        return "Database not initialized"
    
    print(f"📄 Retrieving relevant data...", end=" ", flush=True)
    
    try:
        # Keep chat reads fresh when using long-lived sessions.
        try:
            _session.rollback()
        except Exception:
            pass
        try:
            _session.expire_all()
        except Exception:
            pass

        query_lower = user_query.lower()
        
        # ── 1. Name-based search first ─────────────────────────────────────
        # Extract meaningful tokens (>2 chars, skip common stop words)
        _STOP = {'for', 'the', 'and', 'what', 'when', 'does', 'is', 'are',
                 'will', 'has', 'have', 'eol', 'eos', 'end', 'life', 'of',
                 'support', 'date', 'about', 'can', 'you', 'tell', 'me'}
        tokens = [t for t in query_lower.split() if len(t) > 2 and t not in _STOP]
        
        name_results = []
        if tokens:
            name_filters = [func.lower(ProductEOS.name).contains(token) for token in tokens]
            name_results = (
                _session.query(ProductEOS)
                .filter(or_(*name_filters))
                .order_by(ProductEOS.eos_date.asc())
                .limit(limit)
                .all()
            )
        
        # ── 2. Fall back to type/recency filtered list ──────────────────────
        is_hardware = any(word in query_lower for word in ['hardware', 'cpu', 'processor', 'memory', 'server'])
        is_software = any(word in query_lower for word in ['software', 'windows', 'linux', 'sql', 'os'])
        is_recent = any(word in query_lower for word in ['recent', 'latest', 'newest'])
        is_oldest = any(word in query_lower for word in ['oldest', 'first'])
        
        fallback_query = _session.query(ProductEOS)
        if is_hardware:
            fallback_query = fallback_query.filter(ProductEOS.hardware_software == 'Hardware')
        elif is_software:
            fallback_query = fallback_query.filter(ProductEOS.hardware_software == 'Software')
        if is_oldest:
            fallback_query = fallback_query.order_by(ProductEOS.eos_date.asc())
        elif is_recent:
            fallback_query = fallback_query.order_by(ProductEOS.eos_date.desc())
        else:
            fallback_query = fallback_query.order_by(ProductEOS.eos_date.asc())
        fallback_results = fallback_query.limit(limit).all()
        
        # Merge: name matches first, then fill with fallback (deduplicated)
        seen_ids = {p.id for p in name_results}
        combined = list(name_results)
        for p in fallback_results:
            if p.id not in seen_ids:
                combined.append(p)
                seen_ids.add(p.id)
        results = combined[:limit]
        
        print(f"✓ ({len(results)} products)")
        
        if not results:
            return "No matching products found in the database."
        
        context = "Database Results:\n\n"
        for i, product in enumerate(results, 1):
            context += f"{i}. {product.name}\n"
            context += f"   Type: {product.hardware_software}\n"
            context += f"   Summary: {product.summary}\n"
            context += f"   EOS Date: {product.eos_date.isoformat()}\n"
            context += f"   Confidence: {product.confidence * 100:.0f}%\n"
            
            if product.support_tiers:
                context += f"   Support Tiers:\n"
                for tier in product.support_tiers:
                    context += f"      - {tier.tier}: {tier.end_date.isoformat()}\n"
            context += "\n"
        
        return context
        
    except Exception as e:
        print(f"❌")
        return f"Error retrieving data: {str(e)}"


def _context_has_results(context: str) -> bool:
    """Return True if context contains concrete DB product rows."""
    if not context:
        return False
    if context in {"No matching products found in the database.", "Database not initialized"}:
        return False
    return "Database Results:" in context and bool(re.search(r"\n\d+\.\s+", context))


def _looks_like_missing_data_response(response_text: str) -> bool:
    """Detect model responses that incorrectly claim DB data is unavailable."""
    if not response_text:
        return False
    normalized = response_text.lower()
    miss_patterns = [
        "not in the current database",
        "not in the database",
        "information isn't in the current database",
        "information is not in the current database",
        "data is not available",
        "not available in the database",
        "consult the vendor",
        "add that asset"
    ]
    return any(p in normalized for p in miss_patterns)


def _synthesize_response_from_context(user_message: str, context: str) -> str:
    """Build a deterministic answer from retrieved rows when model grounding fails."""
    products = []
    blocks = re.split(r"\n(?=\d+\.\s+)", context)
    for block in blocks:
        name_match = re.search(r"^\s*\d+\.\s+(.+)$", block, flags=re.MULTILINE)
        type_match = re.search(r"^\s*Type:\s+(.+)$", block, flags=re.MULTILINE)
        eos_match = re.search(r"^\s*EOS Date:\s+(.+)$", block, flags=re.MULTILINE)
        summary_match = re.search(r"^\s*Summary:\s+(.+)$", block, flags=re.MULTILINE)
        if not name_match:
            continue
        products.append({
            "name": name_match.group(1).strip(),
            "type": type_match.group(1).strip() if type_match else "Unknown",
            "eos": eos_match.group(1).strip() if eos_match else "Unknown",
            "summary": summary_match.group(1).strip() if summary_match else ""
        })

    if not products:
        return "I found related entries in the database, but I could not format a reliable answer from them. Please try your query again with the exact asset name."

    lines = [
        "# Asset Lifecycle Result",
        f"Based on current database entries related to your query \"{user_message}\":",
        "",
        "| Asset | Type | EOS Date |",
        "|---|---|---|",
    ]
    for p in products[:3]:
        lines.append(f"| {p['name']} | {p['type']} | {p['eos']} |")

    primary = products[0]
    if primary["summary"]:
        lines.extend([
            "",
            "## Notes",
            f"- {primary['summary']}"
        ])

    return "\n".join(lines)



# ═══════════════════════════════════════════════════════════════════════════
# Unified ChatSession Class
# ═══════════════════════════════════════════════════════════════════════════

class GeminiChatSession:
    """
    Chat session using Google Gemini backend.
    Includes RAG database retrieval, conversation history, and persistent storage.
    """
    
    def __init__(self, session_id: Optional[str] = None, db_session_override=None):
        """
        Initialize chat session with Gemini backend.
        
        Args:
            session_id: Optional session ID for persistence (auto-generated if not provided)
            db_session_override: SQLAlchemy session to use for RAG (falls back to module-level session)
        """
        self.backend = "gemini"
        self._db_session_override = db_session_override
        self.gemini_client = None
        self.gemini_chat = None
        
        # Conversation history tracking
        self.conversation_history: List[Dict[str, str]] = []  # List of {"role": "user"|"assistant", "content": str}
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_file = f"{CHAT_HISTORY_DIR}/{self.session_id}.json"
        
        # Token tracking for conversation (not API calls)
        self.conversation_tokens = 0  # Tokens used in user + assistant messages
        
        # Load previous history if session exists
        self._load_history()
        
        self._init_gemini()
    
    def _init_gemini(self):
        """Initialize Gemini backend with API credential validation."""
        print("🔧 Initializing Gemini...", end=" ")
        try:
            from google.genai import types
            keys, _ = keys_and_prompt_setup(prompt_path='prompts/guardrail.txt')
            self.gemini_client, _ = chat_client_setup(keys)
            
            scraper_client = types.Tool(google_search=types.GoogleSearch())
            
            # Load formatting requirements
            formatting_instruction = """You are an IT asset lifecycle advisor. Your sole purpose is to answer questions about hardware and software End-of-Life (EOS) dates, support status, and related lifecycle information.

You will be provided with product data from a database as context. Answer questions based ONLY on this provided data.

FORMATTING REQUIREMENTS (ALWAYS APPLY):
- Format all responses using valid Markdown syntax
- Use **bold** for important terms, product names, and key values
- Use proper heading levels: # Main Question, ## Details, ### Sub-details
- Use bullet points (- item) for unordered lists
- Use numbered lists (1. item) when showing steps, ranked items, or multiple values
- When presenting data in tabular format, ALWAYS use Markdown tables with | separators
- Table format: | Header1 | Header2 | Header3 | followed by |---|---|---| then data rows
- Use code blocks (```text or ```json) for technical details, model numbers, or formatted data
- Use line breaks between sections for readability
- Format dates clearly: YYYY-MM-DD or Month Day, Year
- Only provide structured, readable output — NO raw JSON, NO unformatted text

"""
            
            # Load database guardrail rules from file - with validation
            db_guardrail_path = SCRIPT_DIR / 'prompts' / 'db_guardrail.txt'
            db_guardrail = ""
            try:
                with open(db_guardrail_path, 'r') as f:
                    db_guardrail = f.read().strip()
                if not db_guardrail:
                    raise ValueError("db_guardrail.txt is empty")
                print(f"✓", end=" ")
                print("(guardrails loaded)")
            except FileNotFoundError:
                raise RuntimeError(f"CRITICAL: Database guardrail file not found at {db_guardrail_path}. This file is essential for security. Please ensure it exists with proper content.")
            except ValueError as ve:
                raise RuntimeError(f"CRITICAL: Database guardrail file is empty: {db_guardrail_path}. Please add guardrail rules.")
            except Exception as e:
                print(f"⚠ Could not load db_guardrail.txt: {e}")
            
            system_instruction = formatting_instruction + db_guardrail

            chat_config = types.GenerateContentConfig(
                tools=[scraper_client],
                system_instruction=system_instruction
            )
            
            self.gemini_chat = self.gemini_client.chats.create(
                model=GEMINI_MODEL,
                config=chat_config
            )
            
            # HIGH #6 FIX: Validate API credentials with test call
            print("✓", end=" ")
            print("(validating API)", end=" ")
            try:
                test_response = self._send_gemini_with_timeout(
                    "Respond with just 'OK' to test the connection.",
                    "",
                    timeout=10
                )
                if test_response is None:
                    raise RuntimeError("API validation failed: timed out")
                if not hasattr(test_response, 'text'):
                    raise RuntimeError("API validation failed: invalid response object")
                print("✓")
            except Exception as e:
                raise RuntimeError(f"API credential test failed: {e}. Please verify your GEMINI_API_KEY.")
            
            # Token tracking for Gemini
            self.estimated_tokens_used = 0
            self.max_tokens_available = GEMINI_CONTEXT_WINDOW
            
        except Exception as e:
            print(f"❌ {e}")
            raise
    

    def _load_history(self):
        """Load conversation history from disk if it exists."""
        session_file_path = Path(self.session_file)
        if session_file_path.exists():
            try:
                with open(session_file_path, 'r') as f:
                    data = json.load(f)
                    self.conversation_history = data.get('history', [])
                    if self.conversation_history:
                        print(f"📜 Loaded {len(self.conversation_history)} previous message(s)")
                        # Recalculate conversation tokens from loaded history
                        self.conversation_tokens = self._count_conversation_tokens()
            except Exception as e:
                print(f"⚠ Could not load history: {e}")
    
    def _save_history(self):
        """Save conversation history to disk with file locking for concurrent access."""
        try:
            session_file_path = Path(self.session_file)
            session_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # HIGH #10 FIX: File locking for concurrent chat session writes
            lock_file = session_file_path.with_suffix('.lock')
            max_wait = 5  # seconds
            start_time = time.time()
            
            # Wait for lock (simple file-based locking)
            while lock_file.exists() and (time.time() - start_time) < max_wait:
                time.sleep(0.1)
            
            # Create lock file
            lock_file.touch(exist_ok=True)
            
            try:
                # Write history atomically (write to temp file, then rename)
                temp_file = session_file_path.with_suffix('.tmp')
                with open(temp_file, 'w') as f:
                    json.dump({
                        'session_id': self.session_id,
                        'backend': self.backend,
                        'model': GEMINI_MODEL,
                        'created': datetime.now().isoformat(),
                        'history': self.conversation_history
                    }, f, indent=2)
                # Atomic rename
                temp_file.replace(session_file_path)
            finally:
                # Remove lock file
                try:
                    lock_file.unlink()
                except:
                    pass
        except Exception as e:
            print(f"⚠ Could not save history: {e}")
    

    def send_message(self, user_message: str, use_rag: bool = True) -> Dict:
        """
        Send a message and get a response with conversation awareness.
        
        Args:
            user_message: The user's input
            use_rag: Whether to retrieve database context first
            
        Returns:
            dict with 'success', 'response', and metadata
        """
        # Step 1: Add user message to history
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })
        # Update token count for this message
        self.conversation_tokens += len(user_message) // 4  # Rough token estimate
        
        # Step 2: Check if query is too vague (trying to get bulk data)
        context = ""
        if use_rag:
            if is_vague_query(user_message):
                # Refuse to retrieve database for vague queries
                vague_response = "I can only provide lifecycle information for a specific, named asset. Please provide the name of the asset you'd like to look up."
                
                # Add this response to history
                self.conversation_history.append({
                    "role": "assistant",
                    "content": vague_response
                })
                self.conversation_tokens += len(vague_response) // 4
                
                # Save history
                self._save_history()
                
                return {
                    'success': True,
                    'response': vague_response,
                    'backend': 'Validation',
                    'context_used': False,
                    'tokens_used': self.estimated_tokens_used,
                    'history_length': len(self.conversation_history),
                    'conversation_tokens': self.conversation_tokens
                }
            else:
                # Retrieve database context for specific queries - limit to 3 products max
                context = retrieve_relevant_products(user_message, limit=3, session_override=self._db_session_override)
        
        # Step 3: Send to Gemini
        result = self._send_gemini(user_message, context)

        # If retrieval found DB rows but model claims data is missing,
        # return a deterministic response from retrieved context instead.
        if (
            result.get('success')
            and _context_has_results(context)
            and _looks_like_missing_data_response(result.get('response', ''))
        ):
            result['response'] = _synthesize_response_from_context(user_message, context)
            result['backend'] = 'RAG-Guardrail'
        
        # Step 4: Add assistant response to history if successful
        if result['success'] and result['response']:
            self.conversation_history.append({
                "role": "assistant",
                "content": result['response']
            })
            # Update token count for assistant response
            self.conversation_tokens += len(result['response']) // 4  # Rough token estimate
        
        # Step 5: Save history
        self._save_history()
        
        # Add history info to result
        result['history_length'] = len(self.conversation_history)
        result['conversation_tokens'] = self.conversation_tokens
        
        return result
    
    def _send_gemini_with_timeout(self, user_message: str, context: str, timeout: int = 30) -> Dict:
        """Send message to Gemini with timeout protection.
        
        HIGH #9 FIX: Wraps API call with timeout to prevent hanging requests.
        """
        try:
            import signal
            
            def timeout_handler(signum, frame):
                raise TimeoutError(f"Gemini API call exceeded {timeout}s timeout")
            
            # Set timeout (only works on Unix-like systems)
            old_handler = None
            try:
                old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(timeout)
            except (AttributeError, ValueError):
                # Windows or signal not available - use simple time check instead
                pass
            
            try:
                # Build message with strict grounding rules when DB context exists.
                message_to_send = user_message
                if context and context != "No matching products found in the database.":
                    message_to_send = (
                        "Use ONLY the database context below as source of truth for asset existence and lifecycle dates. "
                        "If products are listed in the context, do NOT claim they are missing from the database. "
                        "Answer the user's question directly from those listed entries.\\n\\n"
                        f"Context from database:\\n{context}\\n\\n"
                        f"User question:\\n{user_message}"
                    )
                
                response = self.gemini_chat.send_message(message_to_send)
                
                # Cancel timeout
                try:
                    signal.alarm(0)
                except (AttributeError, ValueError):
                    pass
                
                return response
            except TimeoutError:
                raise
            finally:
                # Restore old handler
                if old_handler is not None:
                    signal.signal(signal.SIGALRM, old_handler)
        except TimeoutError as te:
            return None
        except Exception as e:
            raise
    
    def _send_gemini(self, user_message: str, context: str) -> Dict:
        """Send message to Gemini backend. Gemini chat maintains history internally.
        
        IMPORTANT: We do NOT reconstruct and send full conversation history.
        The self.gemini_chat object (Google's native chat interface) maintains 
        state internally and preserves context across calls. Sending full history
        would waste tokens (costs grow exponentially) and increase API latency.
        
        Instead, we send only:
        - RAG context (database results, fresh each call)
        - Current user message
        - Let Gemini handle the conversation state
        """
        spinner = Spinner("Gemini is thinking")
        spinner.start()
        
        try:
            # Build message with context if available
            message_parts = []
            
            if context and context != "No matching products found in the database.":
                message_parts.append(f"Context from database:\n{context}")
            
            # Send ONLY current message (not full history)
            # Gemini chat maintains state automatically
            message_parts.append(user_message)
            full_message = "\n\n".join(message_parts)
            
            # HIGH #9 FIX: Send with timeout protection (30 second default)
            try:
                response = self._send_gemini_with_timeout(user_message, context, timeout=30)
                if response is None:
                    raise TimeoutError("Gemini API call timed out")
            except TimeoutError as te:
                return {
                    'success': False,
                    'response': None,
                    'backend': 'Gemini',
                    'error': f"API timeout: {str(te)}. The Gemini service is not responding. Please try again."
                }
            
            # Validate response before accessing text
            if not response or not hasattr(response, 'text'):
                raise ValueError("Invalid response from Gemini API: missing text attribute")
            response_text = response.text
            
            # Estimate tokens
            self.estimated_tokens_used += len(full_message) // 4  # Rough estimate
            self.estimated_tokens_used += len(response_text) // 4
            
            return {
                'success': True,
                'response': response_text,
                'backend': 'Gemini',
                'model': GEMINI_MODEL,
                'context_used': bool(context and context != "No matching products found in the database."),
                'tokens_used': self.estimated_tokens_used
            }
            
        except Exception as e:
            return {
                'success': False,
                'response': None,
                'backend': 'Gemini',
                'error': str(e)
            }
        finally:
            spinner.stop()
    

    def get_status(self) -> Dict:
        """Get current session status."""
        status = {
            'backend': self.backend.upper(),
            'model': GEMINI_MODEL,
            'tokens_used': self.estimated_tokens_used,
            'tokens_available': self.max_tokens_available,
            'context_usage_percent': (self.estimated_tokens_used / self.max_tokens_available) * 100
        }
        
        return status
    
    def _count_conversation_tokens(self) -> int:
        """Count estimated tokens in current conversation history.
        Uses rough estimate: 1 token ≈ 4 characters."""
        total = 0
        for msg in self.conversation_history:
            total += len(msg.get('content', '')) // 4
        return total
    
    def get_conversation_tokens(self) -> int:
        """Return current conversation token count."""
        return self.conversation_tokens
    
    def get_history(self) -> List[Dict[str, str]]:
        """Get full conversation history."""
        return self.conversation_history
    
    def get_history_text(self) -> str:
        """Get formatted conversation history for display."""
        if not self.conversation_history:
            return "No messages yet."
        
        text = ""
        for i, msg in enumerate(self.conversation_history, 1):
            role = "You" if msg['role'] == 'user' else "AI"
            preview = msg['content'][:100] + "..." if len(msg['content']) > 100 else msg['content']
            text += f"{i}. [{role}] {preview}\n"
        return text
    
    def clear_history(self):
        """Clear conversation history but keep the session file."""
        self.conversation_history = []
        self.conversation_tokens = 0
        self._save_history()
        return "✓ Conversation history cleared"
    
    def reset(self):
        """Clear session and start fresh."""
        self.conversation_history = []
        self._save_history()
        self._init_gemini()
        return "✓ Chat session reset with clear history"


# ═══════════════════════════════════════════════════════════════════════════
# Interactive CLI
# ═══════════════════════════════════════════════════════════════════════════

def list_sessions() -> List[str]:
    """List all available chat session files."""
    try:
        files = Path(CHAT_HISTORY_DIR).glob("*.json")
        sessions = sorted([f.stem for f in files], reverse=True)
        return sessions
    except:
        return []


def load_session(session_id: str) -> Optional[GeminiChatSession]:
    """Load a previous chat session."""
    try:
        session = GeminiChatSession(session_id=session_id)
        return session
    except Exception as e:
        print(f"❌ Failed to load session: {e}")
        return None


def interactive_chat():
    """Start fresh interactive chat session with Gemini backend."""
    print("\n" + "=" * 80)
    print("  Chat with Gemini")
    print("=" * 80)
    print("Commands:")
    print("  'exit' or 'quit'  - End the conversation")
    print("  'history'         - Show conversation history")
    print("  'clear'           - Clear conversation history and restart")
    print("  'status'          - Show session status & token usage")
    print("  'schema'          - Show database schema")
    print("  'rag on/off'      - Toggle database context retrieval")
    print("=" * 80 + "\n")
    
    # Create fresh session
    try:
        session = GeminiChatSession()
        print(f"📝 New session started. Session ID: {session.session_id}\n")
    except Exception as e:
        print(f"❌ Failed to initialize Gemini: {e}")
        return
    
    use_rag = True
    
    while True:
        try:
            user_input = input("You: ").strip()
            
            if not user_input:
                continue
            
            # Handle commands
            if user_input.lower() in ['exit', 'quit']:
                print(f"\n✓ Conversation saved to: {session.session_file}")
                print("Goodbye!")
                break
            
            if user_input.lower() == 'history':
                print("\n📋 Conversation History:")
                print(session.get_history_text())
                print()
                continue
            
            if user_input.lower() == 'clear':
                print(session.clear_history())
                print()
                continue
            
            if user_input.lower() == 'status':
                status = session.get_status()
                print(f"\n📊 Status:")
                print(f"   Session ID: {session.session_id}")
                print(f"   Messages: {len(session.conversation_history)}")
                for key, value in status.items():
                    print(f"   {key}: {value}")
                print()
                continue
            
            if user_input.lower() == 'schema':
                print("\n" + db_schema)
                continue
            
            if user_input.lower() == 'rag on':
                use_rag = True
                print("✓ RAG (database context) enabled\n")
                continue
            
            if user_input.lower() == 'rag off':
                use_rag = False
                print("✓ RAG disabled (direct queries only)\n")
                continue
            
            # Send message with conversation awareness
            result = session.send_message(user_input, use_rag=use_rag)
            
            if result['success']:
                print(f"\n{result['backend']}: {result['response']}\n")
                if result.get('context_used'):
                    print(f"[Context used • Message {result['history_length']}]\n")
                else:
                    print(f"[Message {result['history_length']}]\n")
            else:
                print(f"\n❌ Error: {result['error']}\n")
        
        except KeyboardInterrupt:
            print(f"\n\n✓ Conversation saved")
            print("Interrupted. Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ Unexpected error: {e}\n")


# ═══════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print(" Chat with Gemini - Conversational AI with RAG")
    print("=" * 80 + "\n")
    
    # Initialize database
    if not init_database():
        print("\n❌ Database initialization failed. Exiting.")
        exit(1)
    
    print()
    
    # Start interactive chat session
    interactive_chat()
