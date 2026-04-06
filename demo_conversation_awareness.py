"""
Demo: Conversation Awareness with Persistent Storage
Shows how UnifiedChatSession maintains conversation context across turns
"""

from unified_chat import UnifiedChatSession, init_database

# Initialize database first
print("\n" + "=" * 80)
print("  Unified Chat - Conversation Awareness Demo")
print("=" * 80 + "\n")

if not init_database():
    print("❌ Failed to initialize database")
    exit(1)

print("-" * 80)
print("Demo: Multi-Turn Conversation with Context Awareness")
print("-" * 80 + "\n")

try:
    # Create a Gemini session
    print("🔧 Creating a new chat session...\n")
    session = UnifiedChatSession(backend="gemini")
    print(f"📝 Session ID: {session.session_id}\n")
    
    # First turn - ask about hardware
    print("=" * 80)
    print("💬 TURN 1: Initial query about hardware")
    print("=" * 80)
    print("\nYou: What are the oldest hardware products in the database?\n")
    
    result1 = session.send_message("What are the oldest hardware products in the database?", use_rag=True)
    
    if result1['success']:
        response1 = result1['response']
        print(f"AI: {response1[:400]}...\n")
        print(f"📊 Conversation state: {result1['history_length']} messages saved\n")
    else:
        print(f"❌ Error: {result1['error']}\n")
        exit(1)
    
    # Second turn - follow-up question that relies on context
    print("=" * 80)
    print("💬 TURN 2: Follow-up question (context-aware)")
    print("=" * 80)
    print("\nYou: When did the oldest one reach end of support?\n")
    print("⚠️  Note: This question references 'the oldest one' from previous response")
    print("   The AI should remember and understand the context!\n")
    
    result2 = session.send_message("When did the oldest one reach end of support?", use_rag=False)
    
    if result2['success']:
        response2 = result2['response']
        print(f"AI: {response2[:400]}...\n")
        print(f"📊 Conversation state: {result2['history_length']} messages saved\n")
    else:
        print(f"❌ Error: {result2['error']}\n")
    
    # Third turn - another follow-up
    print("=" * 80)
    print("💬 TURN 3: Another context-aware follow-up")
    print("=" * 80)
    print("\nYou: What support tiers did it have?\n")
    
    result3 = session.send_message("What support tiers did it have?", use_rag=True)
    
    if result3['success']:
        response3 = result3['response']
        print(f"AI: {response3[:400]}...\n")
        print(f"📊 Conversation state: {result3['history_length']} messages saved\n")
    else:
        print(f"❌ Error: {result3['error']}\n")
    
    # Show full conversation history
    print("=" * 80)
    print("📋 Full Conversation History (Persistent)")
    print("=" * 80 + "\n")
    print(session.get_history_text())
    
    # Show session stats
    print("\n" + "=" * 80)
    print("📊 Session Statistics")
    print("=" * 80)
    status = session.get_status()
    print(f"\nSession Details:")
    print(f"  Session ID: {session.session_id}")
    print(f"  Backend: {status['backend']}")
    print(f"  Total Messages: {len(session.conversation_history)}")
    print(f"  Tokens Used: {status['tokens_used']:,} / {status['tokens_available']:,}")
    print(f"  Context Usage: {status['context_usage_percent']:.1f}%")
    print(f"\nPersistent Storage:")
    print(f"  Saved to: {session.session_file}")
    print(f"  ✓ Can resume this conversation later with the same session ID\n")
    
    # Demo persistence - load the session again
    print("=" * 80)
    print("✓ Demonstrating Persistence")
    print("=" * 80 + "\n")
    print(f"Loading the same session again: {session.session_id}\n")
    
    # Create a new session object with the same ID
    resumed_session = UnifiedChatSession(backend="gemini", session_id=session.session_id)
    print(f"✓ Loaded session with {len(resumed_session.conversation_history)} previous messages\n")
    
    # Continue the conversation
    print("Continuing conversation from where we left off...")
    print("You: Can you summarize what we discussed about those old products?\n")
    
    result4 = resumed_session.send_message("Can you summarize what we discussed about those old products?", use_rag=False)
    
    if result4['success']:
        print(f"AI: {result4['response'][:400]}...\n")
        print(f"📊 Total messages in session: {result4['history_length']}\n")
    
except Exception as e:
    print(f"❌ Error during demo: {e}\n")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("Demo Complete!")
print("=" * 80)
print("\nKey Features Demonstrated:")
print("  ✓ Multi-turn conversations with context awareness")
print("  ✓ Follow-up questions that reference previous responses")
print("  ✓ Persistent storage of conversation history")
print("  ✓ Session resumption and continuation")
print("  ✓ RAG integration for database context\n")
print("Try the interactive mode:")
print("  python unified_chat.py\n")
