"""
Unified Chat Interface - Choose between Ollama and Gemini
Combines RAG database retrieval with your choice of backend model
"""

import json
import requests
import warnings
import os
from typing import Optional, Dict, List
from datetime import datetime, date
from sqlalchemy import create_engine, text
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

# Ollama Configuration
OLLAMA_API_BASE = "http://localhost:11434"
OLLAMA_API_ENDPOINT = f"{OLLAMA_API_BASE}/api/generate"
OLLAMA_MODELS_ENDPOINT = f"{OLLAMA_API_BASE}/api/tags"
OLLAMA_DEFAULT_MODEL = "gemma4:e2b"

# Gemini Configuration (loaded at runtime)
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_CONTEXT_WINDOW = 1_000_000
GEMINI_SAFETY_THRESHOLD = 0.85

# System Prompts
OLLAMA_SYSTEM_PROMPT = """You are a helpful AI assistant that answers questions about hardware and software End-of-Life (EOS) information.

You will be provided with relevant product data from the database. Answer the user's question based ONLY on the data provided below.

If the data doesn't contain the answer, clearly state that the information is not available.
Be concise and clear in your responses.
Highlight important dates and support status information."""

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


def retrieve_relevant_products(user_query: str, limit: int = 10) -> str:
    """Retrieve relevant products from database based on user query keywords."""
    if not db_session:
        return "Database not initialized"
    
    print(f"📄 Retrieving relevant data...", end=" ", flush=True)
    
    try:
        query_lower = user_query.lower()
        
        # Detect what user is looking for
        is_hardware = any(word in query_lower for word in ['hardware', 'cpu', 'processor', 'memory', 'server'])
        is_software = any(word in query_lower for word in ['software', 'windows', 'linux', 'sql', 'os'])
        is_eol = any(word in query_lower for word in ['end', 'eol', 'support', 'expir'])
        is_recent = any(word in query_lower for word in ['recent', 'latest', 'newest'])
        is_oldest = any(word in query_lower for word in ['oldest', 'first'])
        
        query = db_session.query(ProductEOS)
        
        if is_hardware:
            query = query.filter(ProductEOS.hardware_software == 'Hardware')
        elif is_software:
            query = query.filter(ProductEOS.hardware_software == 'Software')
        
        if is_oldest:
            query = query.order_by(ProductEOS.eos_date.asc())
        elif is_recent:
            query = query.order_by(ProductEOS.eos_date.desc())
        else:
            query = query.order_by(ProductEOS.eos_date.asc())
        
        results = query.limit(limit).all()
        
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
# Ollama Functions
# ═══════════════════════════════════════════════════════════════════════════

def check_ollama_connection() -> bool:
    """Check if Ollama server is running."""
    try:
        response = requests.get(f"{OLLAMA_API_BASE}/api/status", timeout=3)
        return response.status_code == 200
    except:
        return False


def get_available_models() -> list:
    """Get list of available models from Ollama."""
    try:
        response = requests.get(OLLAMA_MODELS_ENDPOINT, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return [model['name'] for model in data.get('models', [])]
        return []
    except Exception as e:
        print(f"⚠ Error fetching models: {e}")
        return []


def query_ollama(user_input: str, context: str = "", model: str = OLLAMA_DEFAULT_MODEL) -> Dict:
    """Send a query to Ollama and get a response."""
    print(f"🤖 Querying {model}...", end=" ", flush=True)
    
    try:
        if context:
            full_prompt = f"{OLLAMA_SYSTEM_PROMPT}\n\nRELEVANT DATA FROM DATABASE:\n{context}\n\nUser Question: {user_input}"
        else:
            full_prompt = f"{OLLAMA_SYSTEM_PROMPT}\n\nUser Question: {user_input}"
        
        payload = {
            'model': model,
            'prompt': full_prompt,
            'stream': False,
            'temperature': 0.3,
            'top_p': 0.9,
            'top_k': 40,
            'num_ctx': 4096,
        }
        
        response = requests.post(
            OLLAMA_API_ENDPOINT,
            json=payload,
            timeout=180
        )
        
        if response.status_code == 200:
            data = response.json()
            result_text = data.get('response', '').strip()
            print("✓")
            return {
                'success': True,
                'response': result_text,
                'model': model,
                'error': None
            }
        else:
            print(f"❌ (Status {response.status_code})")
            return {
                'success': False,
                'response': None,
                'model': model,
                'error': f"HTTP {response.status_code}"
            }
            
    except requests.Timeout:
        print("❌ (Timeout)")
        return {
            'success': False,
            'response': None,
            'model': model,
            'error': 'Request timed out'
        }
    except Exception as e:
        print(f"❌ ({type(e).__name__})")
        return {
            'success': False,
            'response': None,
            'model': model,
            'error': str(e)
        }


# ═══════════════════════════════════════════════════════════════════════════
# Unified ChatSession Class
# ═══════════════════════════════════════════════════════════════════════════

class UnifiedChatSession:
    """
    Unified chat session that works with either Ollama or Gemini backend.
    Includes RAG database retrieval, conversation history, and persistent storage.
    """
    
    def __init__(self, backend: str = "gemini", model: Optional[str] = None, system_prompt: Optional[str] = None, session_id: Optional[str] = None):
        """
        Initialize chat session with specified backend.
        
        Args:
            backend: "ollama" or "gemini"
            model: Specific model to use (optional)
            system_prompt: Optional custom system prompt
            session_id: Optional session ID for persistence (auto-generated if not provided)
        """
        self.backend = backend.lower()
        self.model = model
        self.system_prompt = system_prompt
        self.gemini_client = None
        self.gemini_chat = None
        self.ollama_model = OLLAMA_DEFAULT_MODEL
        
        # Conversation history tracking
        self.conversation_history: List[Dict[str, str]] = []  # List of {"role": "user"|"assistant", "content": str}
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_file = f"{CHAT_HISTORY_DIR}/{self.session_id}.json"
        
        # Load previous history if session exists
        self._load_history()
        
        if self.backend == "gemini":
            self._init_gemini()
        elif self.backend == "ollama":
            self._init_ollama()
        else:
            raise ValueError(f"Unknown backend: {backend}")
    
    def _init_gemini(self):
        """Initialize Gemini backend."""
        print("🔧 Initializing Gemini...", end=" ")
        try:
            from google.genai import types
            keys, _ = keys_and_prompt_setup(prompt_path='prompts/guardrail.txt')
            self.gemini_client, _ = chat_client_setup(keys)
            
            scraper_client = types.Tool(google_search=types.GoogleSearch())
            chat_config = types.GenerateContentConfig(tools=[scraper_client])
            
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
    
    def _init_ollama(self):
        """Initialize Ollama backend."""
        print("🔗 Checking Ollama...", end=" ")
        if not check_ollama_connection():
            print("❌ Ollama not found at", OLLAMA_API_BASE)
            raise ConnectionError("Ollama server not running")
        print("✓")
        
        print("📦 Fetching available models...", end=" ")
        models = get_available_models()
        if not models:
            print("❌ No models found")
            raise RuntimeError("No Ollama models available")
        print(f"✓ ({len(models)} models)")
        
        if self.model and self.model in models:
            self.ollama_model = self.model
        elif self.model:
            matches = [m for m in models if self.model in m]
            self.ollama_model = matches[0] if matches else models[0]
        else:
            self.ollama_model = models[0] if OLLAMA_DEFAULT_MODEL not in models else OLLAMA_DEFAULT_MODEL
        
        print(f"✓ Using model: {self.ollama_model}")
    
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
                    'model': self.model or self.ollama_model,
                    'created': datetime.now().isoformat(),
                    'history': self.conversation_history
                }, f, indent=2)
        except Exception as e:
            print(f"⚠ Could not save history: {e}")
    
    def _build_conversation_context(self) -> str:
        """Build conversation context from history for Ollama."""
        if not self.conversation_history:
            return ""
        
        context = "Previous conversation:\n"
        for msg in self.conversation_history[-6:]:  # Last 6 messages for context
            role = "User" if msg['role'] == 'user' else "Assistant"
            context += f"{role}: {msg['content']}\n"
        return context
    
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
            context = retrieve_relevant_products(user_message, limit=10)
        
        # Step 3: Send to backend
        if self.backend == "gemini":
            result = self._send_gemini(user_message, context)
        else:
            result = self._send_ollama(user_message, context)
        
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
        """Send message to Gemini backend with conversation awareness."""
        spinner = Spinner("Gemini is thinking")
        spinner.start()
        
        try:
            # Build message with context if available
            message_parts = []
            
            if context and context != "No matching products found in the database.":
                message_parts.append(f"Context from database:\n{context}")
            
            # Add conversation context if we have history
            if len(self.conversation_history) > 1:  # More than just the current user message
                conv_context = self._build_conversation_context()
                if conv_context:
                    message_parts.append(conv_context)
            
            message_parts.append(f"Current question: {user_message}")
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
    
    def _send_ollama(self, user_message: str, context: str) -> Dict:
        """Send message to Ollama backend with conversation awareness."""
        # Build full context including conversation history
        full_context = context
        
        # Add conversation history if available
        if len(self.conversation_history) > 1:  # More than just current user message
            conv_context = self._build_conversation_context()
            if conv_context:
                full_context = (conv_context + "\n\n" + context) if context else conv_context
        
        result = query_ollama(user_message, context=full_context, model=self.ollama_model)
        result['backend'] = 'Ollama'
        result['context_used'] = bool(context)
        return result
    
    def get_status(self) -> Dict:
        """Get current session status."""
        status = {
            'backend': self.backend.upper(),
            'model': self.gemini_chat or self.ollama_model
        }
        
        if self.backend == "gemini":
            status['tokens_used'] = self.estimated_tokens_used
            status['tokens_available'] = self.max_tokens_available
            status['context_usage_percent'] = (self.estimated_tokens_used / self.max_tokens_available) * 100
        
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
        
        if self.backend == "gemini":
            self._init_gemini()
            return "✓ Gemini session reset with clear history"
        else:
            return "✓ Ollama session ready for new conversation"


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


def load_session(session_id: str, backend: str, model: Optional[str] = None) -> Optional[UnifiedChatSession]:
    """Load a previous chat session."""
    try:
        session = UnifiedChatSession(backend=backend, model=model, session_id=session_id)
        return session
    except Exception as e:
        print(f"❌ Failed to load session: {e}")
        return None


def interactive_chat(backend: str, model: Optional[str] = None):
    """Start fresh interactive chat session with chosen backend."""
    print("\n" + "=" * 80)
    print(f"  Unified Chat with {backend.upper()}")
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
        session = UnifiedChatSession(backend=backend, model=model)
        print(f"📝 New session started. Session ID: {session.session_id}\n")
    except Exception as e:
        print(f"❌ Failed to initialize {backend}: {e}")
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
    print(" Unified Chat - Conversational AI with RAG")
    print("=" * 80 + "\n")
    
    # Initialize database
    if not init_database():
        print("\n❌ Database initialization failed. Exiting.")
        exit(1)
    
    # Choose backend for new session
    print("🤖 Available backends:")
    print("  1. Gemini (Cloud-based, with web search)")
    print("  2. Ollama (Local inference, offline mode)")
    print()
    
    choice = input("Choose backend (1 or 2): ").strip()
    
    if choice == "1":
        backend = "gemini"
    elif choice == "2":
        backend = "ollama"
    else:
        print("Invalid choice. Defaulting to Gemini.")
        backend = "gemini"
    
    print()
    
    # Start a fresh interactive chat session
    interactive_chat(backend)
