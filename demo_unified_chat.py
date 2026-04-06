"""
Demo script showing how to use UnifiedChatSession
Shows both Gemini and Ollama backends
"""

from unified_chat import UnifiedChatSession, init_database

# Initialize database first
print("\n" + "=" * 80)
print("  Unified Chat Demo")
print("=" * 80 + "\n")

if not init_database():
    print("❌ Failed to initialize database")
    exit(1)

print("\n" + "-" * 80)
print("DEMO 1: Using Gemini with RAG")
print("-" * 80 + "\n")

try:
    # Create Gemini session
    gemini_session = UnifiedChatSession(backend="gemini")
    
    # Example query with database context
    print("Querying: 'What hardware products are becoming obsolete?'\n")
    result = gemini_session.send_message("What hardware products are becoming obsolete?", use_rag=True)
    
    if result['success']:
        print(f"✓ Response from {result['backend']}:")
        print(f"  {result['response'][:200]}...\n")
        print(f"  [Context used: {result['context_used']}, Tokens: {result['tokens_used']}]\n")
    else:
        print(f"❌ Error: {result['error']}\n")
    
    # Show status
    status = gemini_session.get_status()
    print("Session Status:")
    print(f"  Backend: {status['backend']}")
    print(f"  Model: {status['model']}")
    print(f"  Tokens: {status['tokens_used']} / {status['tokens_available']}\n")

except Exception as e:
    print(f"⚠ Gemini demo skipped: {e}\n")

print("\n" + "-" * 80)
print("DEMO 2: Using Ollama with RAG (if available)")
print("-" * 80 + "\n")

try:
    # Create Ollama session
    ollama_session = UnifiedChatSession(backend="ollama")
    
    # Example query with database context
    print("Querying: 'Show me recent software products'\n")
    result = ollama_session.send_message("Show me recent software products", use_rag=True)
    
    if result['success']:
        print(f"✓ Response from {result['backend']}:")
        print(f"  {result['response'][:200]}...\n")
        print(f"  [Context used: {result['context_used']}, Model: {result['model']}]\n")
    else:
        print(f"❌ Error: {result['error']}\n")

except Exception as e:
    print(f"⚠ Ollama demo skipped: {e}\n")

print("\n" + "=" * 80)
print("To use interactively, run:")
print("  python unified_chat.py")
print("=" * 80 + "\n")
