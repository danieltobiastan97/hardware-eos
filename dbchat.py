"""
Database Chat Interface using Ollama Local Model
Retrieval-Augmented Generation (RAG) Mode: Query database first, then answer with context
"""

import requests
import json
from typing import Optional, Dict, List
from datetime import datetime, date
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import os

# Import database models
from models import ProductEOS, SupportTier, assetCache, Base

# ═══════════════════════════════════════════════════════════════════════════
# Database Configuration
# ═══════════════════════════════════════════════════════════════════════════

# Use relative path to database file in data folder
DATABASE_URL = "sqlite:///./data/asset_cache.db"
DB_PATH = "./data/asset_cache.db"

# Database globals
db_engine = None
db_session = None
db_schema = None


def init_database() -> bool:
    """Initialize database connection and cache schema."""
    global db_engine, db_session, db_schema
    
    print("📊 Initializing database connection...", end=" ")
    try:
        # Create engine using the normalized path
        db_engine = create_engine(DATABASE_URL, echo=False)
        
        # Test connection
        with db_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        # Create session
        Session = sessionmaker(bind=db_engine)
        db_session = Session()
        
        # Cache schema info
        db_schema = get_database_schema()
        
        print("✓")
        print(f"   Database: {DB_PATH}")
        print(f"   Schema: ProductEOS, SupportTier, assetCache tables found")
        return True
        
    except Exception as e:
        print(f"❌ FAILED")
        print(f"   Error: {e}")
        print(f"   Path: {DATABASE_URL}")
        return False


def get_database_schema() -> str:
    """Get database schema information for context."""
    schema = """
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

Table: asset_cache (Legacy)
- id (Integer, Primary Key)
- item_name (String, 100 chars, Unique)
- item_type (String) - 'hardware' or 'software'
- processing_date (DateTime)
- result (String) - JSON result
- status (String) - 'success', 'failed', 'retry'
- error_message (String)
- processing_time (Float)
"""
    return schema


# ═══════════════════════════════════════════════════════════════════════════
# Ollama Configuration
# ═══════════════════════════════════════════════════════════════════════════

OLLAMA_API_BASE = "http://localhost:11434"
OLLAMA_API_ENDPOINT = f"{OLLAMA_API_BASE}/api/generate"
OLLAMA_MODELS_ENDPOINT = f"{OLLAMA_API_BASE}/api/tags"

# Default model - will verify on startup
DEFAULT_MODEL = "gemma4:e2b"

# System prompt for RAG-based answering
SYSTEM_PROMPT = """You are a helpful AI assistant that answers questions about hardware and software End-of-Life (EOS) information.

You will be provided with relevant product data from the database. Answer the user's question based ONLY on the data provided below.

If the data doesn't contain the answer, clearly state that the information is not available.
Be concise and clear in your responses.
Highlight important dates and support status information."""


# ═══════════════════════════════════════════════════════════════════════════
# Ollama API Functions
# ═══════════════════════════════════════════════════════════════════════════

def check_ollama_connection() -> bool:
    """Check if Ollama server is running and accessible."""
    try:
        response = requests.get(f"{OLLAMA_API_BASE}/api/status", timeout=3)
        return response.status_code == 200
    except (requests.ConnectionError, requests.Timeout):
        return False


def get_available_models() -> list:
    """Get list of available models from Ollama."""
    try:
        response = requests.get(OLLAMA_MODELS_ENDPOINT, timeout=5)
        if response.status_code == 200:
            data = response.json()
            # Ollama returns full model names with tags (e.g., "qwen3-coder:latest")
            models = [model['name'] for model in data.get('models', [])]
            return models
        return []
    except Exception as e:
        print(f"⚠ Error fetching models: {e}")
        return []


def init_ollama(model_name: Optional[str] = None) -> bool:
    """
    Initialize Ollama connection and set the model to use.
    
    Args:
        model_name: Name of the model to use. If None, uses DEFAULT_MODEL.
        
    Returns:
        bool: True if successful, False otherwise
    """
    global DEFAULT_MODEL
    
    print("🔗 Checking Ollama connection...", end=" ")
    if not check_ollama_connection():
        print("❌ FAILED")
        print("   Ollama server not found at", OLLAMA_API_BASE)
        print("   Please start Ollama first: ollama serve")
        return False
    print("✓")
    
    print("📦 Fetching available models...", end=" ")
    models = get_available_models()
    if not models:
        print("❌ FAILED")
        print("   No models found. Please load a model in Ollama first.")
        return False
    print(f"✓ Found {len(models)} model(s)")
    
    # Determine which model to use
    selected_model = model_name or DEFAULT_MODEL
    
    # Check if selected model exists
    if selected_model in models:
        DEFAULT_MODEL = selected_model
        print(f"✓ Using model: {DEFAULT_MODEL}")
    else:
        # Model not found - try to find partial match
        matches = [m for m in models if selected_model in m or selected_model.split(':')[0] in m]
        if matches:
            DEFAULT_MODEL = matches[0]
            print(f"⚠ Model '{selected_model}' not found, using closest match: {DEFAULT_MODEL}")
        else:
            # Fall back to first available
            DEFAULT_MODEL = models[0]
            print(f"⚠ Model '{selected_model}' not available, using: {DEFAULT_MODEL}")
    
    return True


def query_ollama(user_input: str, context: str = "", model: Optional[str] = None) -> Dict:
    """
    Send a query to Ollama and get a response with context.
    
    Args:
        user_input: The user's natural language input
        context: Optional context/data from database to provide as context
        model: Model to use (defaults to DEFAULT_MODEL)
        
    Returns:
        dict: {
            'success': bool,
            'response': str (the model's response),
            'model': str (which model was used),
            'error': str (if unsuccessful)
        }
    """
    if not DEFAULT_MODEL and not model:
        return {
            'success': False,
            'response': None,
            'model': None,
            'error': 'Ollama not initialized. Call init_ollama() first.'
        }
    
    model_to_use = model or DEFAULT_MODEL
    
    print(f"\n🤖 Querying {model_to_use}...", end=" ", flush=True)
    
    try:
        # Build prompt with context
        if context:
            full_prompt = f"{SYSTEM_PROMPT}\n\nRELEVANT DATA FROM DATABASE:\n{context}\n\nUser Question: {user_input}"
        else:
            full_prompt = f"{SYSTEM_PROMPT}\n\nUser Question: {user_input}"
        
        payload = {
            'model': model_to_use,
            'prompt': full_prompt,
            'stream': False,
            'temperature': 0.3,  # Slightly higher than SQL generation for natural answers
            'top_p': 0.9,  # Nucleus sampling for better coherence
            'top_k': 40,  # Restrict to top 40 tokens
            'num_ctx': 4096,  # Context window size
        }
        
        response = requests.post(
            OLLAMA_API_ENDPOINT,
            json=payload,
            timeout=180  # 3 minutes for model inference
        )
        
        if response.status_code == 200:
            data = response.json()
            result_text = data.get('response', '').strip()
            print("✓")
            return {
                'success': True,
                'response': result_text,
                'model': model_to_use,
                'error': None
            }
        else:
            print(f"❌ (Status {response.status_code})")
            return {
                'success': False,
                'response': None,
                'model': model_to_use,
                'error': f"HTTP {response.status_code}: {response.text}"
            }
            
    except requests.Timeout:
        print("❌ (Timeout)")
        return {
            'success': False,
            'response': None,
            'model': model_to_use,
            'error': 'Request timed out - model may be processing for too long'
        }
    except Exception as e:
        print(f"❌ ({type(e).__name__})")
        return {
            'success': False,
            'response': None,
            'model': model_to_use,
            'error': str(e)
        }


# ═══════════════════════════════════════════════════════════════════════════
# RAG Retrieval Functions
# ═══════════════════════════════════════════════════════════════════════════

def retrieve_relevant_products(user_query: str, limit: int = 10) -> str:
    """Retrieve relevant products from database based on user query keywords."""
    if not db_session:
        return "Database not initialized"
    
    print(f"\n📄 Retrieving relevant data...", end=" ", flush=True)
    
    try:
        # Convert query to lowercase for matching
        query_lower = user_query.lower()
        
        # Detect what user is looking for
        is_hardware = 'hardware' in query_lower or 'cpu' in query_lower or 'processor' in query_lower or 'memory' in query_lower
        is_software = 'software' in query_lower or 'windows' in query_lower or 'linux' in query_lower or 'sql' in query_lower or 'os' in query_lower
        is_eol = 'end' in query_lower or 'eol' in query_lower or 'support' in query_lower or 'expir' in query_lower
        is_recent = 'recent' in query_lower or 'latest' in query_lower or 'newest' in query_lower
        is_oldest = 'oldest' in query_lower or 'first' in query_lower
        
        # Start with base query
        query = db_session.query(ProductEOS)
        
        # Filter by type if specified
        if is_hardware:
            query = query.filter(ProductEOS.hardware_software == 'Hardware')
        elif is_software:
            query = query.filter(ProductEOS.hardware_software == 'Software')
        
        # Apply sorting
        if is_oldest:
            query = query.order_by(ProductEOS.eos_date.asc())
        elif is_recent:
            query = query.order_by(ProductEOS.eos_date.desc())
        else:
            # Default: by EOS date ascending (soonest first)
            query = query.order_by(ProductEOS.eos_date.asc())
        
        # Limit results
        results = query.limit(limit).all()
        
        print(f"✓ ({len(results)} products)")
        
        # Format results as context
        if not results:
            return "No matching products found in the database."
        
        context = "Database Results:\n\n"
        for i, product in enumerate(results, 1):
            context += f"{i}. {product.name}\n"
            context += f"   Type: {product.hardware_software}\n"
            context += f"   Summary: {product.summary}\n"
            context += f"   EOS Date: {product.eos_date.isoformat()}\n"
            context += f"   Confidence: {product.confidence * 100:.0f}%\n"
            
            # Include support tiers if available
            if product.support_tiers:
                context += f"   Support Tiers:\n"
                for tier in product.support_tiers:
                    context += f"      - {tier.tier}: {tier.end_date.isoformat()}\n"
            context += "\n"
        
        return context
        
    except Exception as e:
        print(f"❌")
        return f"Error retrieving data: {str(e)}"


def retrieve_all_products(hardware_software: Optional[str] = None, limit: int = 10) -> str:
    """Retrieve all products or filtered by type."""
    if not db_session:
        return "Database not initialized"
    
    print(f"\n📄 Retrieving data...", end=" ", flush=True)
    
    try:
        query = db_session.query(ProductEOS)
        
        if hardware_software:
            query = query.filter(ProductEOS.hardware_software == hardware_software)
        
        query = query.order_by(ProductEOS.eos_date.asc()).limit(limit)
        results = query.all()
        
        print(f"✓ ({len(results)} products)")
        
        if not results:
            return "No products found in the database."
        
        context = "Database Results:\n\n"
        for i, product in enumerate(results, 1):
            context += f"{i}. {product.name}\n"
            context += f"   Type: {product.hardware_software}\n"
            context += f"   EOS Date: {product.eos_date.isoformat()}\n"
            context += f"   Summary: {product.summary}\n\n"
        
        return context
        
    except Exception as e:
        print(f"❌")
        return f"Error retrieving data: {str(e)}"


def process_database_query(user_input: str) -> Dict:
    """Process a user query: retrieve data from DB, then let Ollama answer from context."""
    
    # Step 1: Retrieve relevant data from database
    context = retrieve_relevant_products(user_input, limit=10)
    
    # Step 2: Send to Ollama with context for answering
    result = query_ollama(user_input, context=context)
    
    if not result['success']:
        return {
            'success': False,
            'response': result['response'],
            'error': result['error']
        }
    
    return {
        'success': True,
        'response': result['response'],
        'model': result['model'],
        'context_used': context
    }


def interactive_chat():
    """Interactive chat loop with Ollama and database (RAG mode)."""
    print("\n" + "=" * 80)
    print("  Database Chat with Ollama - RAG Mode (Data Retrieval + Answering)")
    print("=" * 80)
    print("\nCommands:")
    print("  'exit' or 'quit'  - End the conversation")
    print("  'models'          - Show available models")
    print("  'schema'          - Show database schema")
    print("  'all'             - Show all products")
    print("=" * 80 + "\n")
    
    while True:
        try:
            user_input = input("You: ").strip()
            
            # Handle commands
            if user_input.lower() in ['exit', 'quit']:
                print("\nGoodbye!")
                break
            
            if user_input.lower() == 'models':
                models = get_available_models()
                print(f"\nAvailable models: {', '.join(models)}")
                print(f"Currently using: {DEFAULT_MODEL}\n")
                continue
            
            if user_input.lower() == 'schema':
                print(db_schema)
                print()
                continue
            
            if user_input.lower() == 'all':
                print(retrieve_all_products(limit=20))
                continue
            
            if not user_input:
                continue
            
            # Process natural language query with RAG
            result = process_database_query(user_input)
            
            if result['success']:
                print(f"\n🤖 Answer:\n{result['response']}\n")
            else:
                print(f"\n❌ Error: {result['error']}\n")
                
        except KeyboardInterrupt:
            print("\n\nInterrupted. Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ Unexpected error: {e}\n")


# ═══════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print(" Initializing Database Chat with Ollama")
    print("=" * 80 + "\n")
    
    # Initialize Database
    if not init_database():
        print("\n❌ Failed to initialize database. Exiting.")
        exit(1)
    
    # Initialize Ollama connection
    if not init_ollama():
        print("\n❌ Failed to initialize Ollama. Exiting.")
        exit(1)
    
    print(f"\n✓ All systems initialized!")
    print(f"✓ Ready to process natural language queries\n")
    
    # Start interactive chat
    interactive_chat()
