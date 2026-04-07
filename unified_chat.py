"""
Gemini Chat Interface with RAG
Combines RAG database retrieval with Google Gemini backend
"""

import json
import requests
import warnings
import os
from typing import Optional, Dict, List
from datetime import datetime, date
from sqlalchemy import create_engine, text, or_, func
from sqlalchemy.orm import sessionmaker
from pathlib import Path

# Suppress warnings
warnings.filterwarnings("ignore", message=".*thought_signature.*")

# Import database models
from models import ProductEOS, SupportTier, assetCache, Base
from prompt import keys_and_prompt_setup, client_setup, Spinner, chat_client_setup

# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

# Database Configuration
DATABASE_URL = "sqlite:///./data/asset_cache.db"
DB_PATH = "./data/asset_cache.db"

# Gemini Configuration
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_CONTEXT_WINDOW = 1_000_000
GEMINI_SAFETY_THRESHOLD = 0.85

# Database globals
db_engine = None
db_session = None
db_schema = None

# Chat history storage
CHAT_HISTORY_DIR = "./chat_sessions"
Path(CHAT_HISTORY_DIR).mkdir(exist_ok=True)

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


def retrieve_relevant_products(user_query: str, limit: int = 10, session_override=None) -> str:
    """Retrieve relevant products from database based on user query keywords."""
    _session = session_override or db_session
    if not _session:
        return "Database not initialized"
    
    print(f"📄 Retrieving relevant data...", end=" ", flush=True)
    
    try:
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
        
        # Load previous history if session exists
        self._load_history()
        
        self._init_gemini()
    
    def _init_gemini(self):
        """Initialize Gemini backend."""
        print("🔧 Initializing Gemini...", end=" ")
        try:
            from google.genai import types
            keys, _ = keys_and_prompt_setup(prompt_path='prompts/guardrail.txt')
            self.gemini_client, _ = chat_client_setup(keys)
            
            scraper_client = types.Tool(google_search=types.GoogleSearch())
            
            system_instruction = """You are an IT asset lifecycle advisor. Your sole purpose is to answer questions about hardware and software End-of-Life (EOS) dates, support status, and related lifecycle information.

You will be provided with product data from a database as context. Answer questions based ONLY on this provided data.

CONSTRAINTS:
- Only discuss EOS, EOL, support dates, and lifecycle information for IT assets
- If asked about your general capabilities, respond: "I'm here to help with questions about asset End-of-Life and support status information."
- Do not provide information unrelated to IT asset lifecycle
- If data is not available, clearly state it and suggest checking vendor documentation
- Be concise and IT-professional in tone"""
            
            chat_config = types.GenerateContentConfig(
                tools=[scraper_client],
                system_instruction=system_instruction
            )
            
            self.gemini_chat = self.gemini_client.chats.create(
                model=GEMINI_MODEL,
                config=chat_config
            )
            
            # Token tracking for Gemini
            self.estimated_tokens_used = 0
            self.max_tokens_available = GEMINI_CONTEXT_WINDOW
            
            print("✓")
            
        except Exception as e:
            print(f"❌ {e}")
            raise
    

    def _load_history(self):
        """Load conversation history from disk if it exists."""
        if os.path.exists(self.session_file):
            try:
                with open(self.session_file, 'r') as f:
                    data = json.load(f)
                    self.conversation_history = data.get('history', [])
                    if self.conversation_history:
                        print(f"📜 Loaded {len(self.conversation_history)} previous message(s)")
            except Exception as e:
                print(f"⚠ Could not load history: {e}")
    
    def _save_history(self):
        """Save conversation history to disk."""
        try:
            with open(self.session_file, 'w') as f:
                json.dump({
                    'session_id': self.session_id,
                    'backend': self.backend,
                    'model': GEMINI_MODEL,
                    'created': datetime.now().isoformat(),
                    'history': self.conversation_history
                }, f, indent=2)
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
        
        # Step 2: Optionally retrieve database context (RAG)
        context = ""
        if use_rag:
            context = retrieve_relevant_products(user_message, limit=10, session_override=self._db_session_override)
        
        # Step 3: Send to Gemini
        result = self._send_gemini(user_message, context)
        
        # Step 4: Add assistant response to history if successful
        if result['success'] and result['response']:
            self.conversation_history.append({
                "role": "assistant",
                "content": result['response']
            })
        
        # Step 5: Save history
        self._save_history()
        
        # Add history info to result
        result['history_length'] = len(self.conversation_history)
        
        return result
    
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
            
            response = self.gemini_chat.send_message(full_message)
            response_text = response.text
            
            # Estimate tokens
            self.estimated_tokens_used += len(full_message) // 4  # Rough estimate
            self.estimated_tokens_used += len(response_text) // 4
            
            return {
                'success': True,
                'response': response_text,
                'backend': 'Gemini',
                'model': GEMINI_MODEL,
                'context_used': bool(context),
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
