"""
Demo: Conversation Awareness Within a Single Session
Shows how UnifiedChatSession maintains context for multi-turn conversations
Each session is independent - starting a new chat = fresh conversation
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
print("Demo: Multi-Turn Conversation (Within Single Session)")
print("-" * 80 + "\n")

try:
    # Create a Gemini session
    print("🔧 Creating a new chat session...\n")
    session = UnifiedChatSession(backend="gemini")
    print(f"📝 Session ID: {session.session_id}")
    print(f"   (This is ONE chat - when you exit, future chats are fresh and independent)\n")
    
    # First turn - ask about hardware
    print("=" * 80)
    print("💬 TURN 1: Initial query about hardware")
    print("=" * 80)
    print("\nYou: What are the oldest hardware products in the database?\n")
    
    result1 = session.send_message("What are the oldest hardware products in the database?", use_rag=True)
    
    if result1['success']:
        response1 = result1['response']
        print(f"AI: {response1[:400]}...\n")
        print(f"📊 Messages in this session: {result1['history_length']}\n")
    else:
        print(f"❌ Error: {result1['error']}\n")
        exit(1)
    
    # Second turn - follow-up question that relies on context
    print("=" * 80)
    print("💬 TURN 2: Follow-up question (AI remembers previous response)")
    print("=" * 80)
    print("\nYou: When did the oldest one reach end of support?\n")
    print("✓ Note: This question references 'the oldest one' from Turn 1")
    print("   Within THIS session, the AI remembers the context!\n")
    
    result2 = session.send_message("When did the oldest one reach end of support?", use_rag=False)
    
    if result2['success']:
        response2 = result2['response']
        print(f"AI: {response2[:400]}...\n")
        print(f"📊 Messages in this session: {result2['history_length']}\n")
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
        print(f"📊 Messages in this session: {result3['history_length']}\n")
    else:
        print(f"❌ Error: {result3['error']}\n")
    
    # Show full conversation history
    print("=" * 80)
    print("📋 Full Conversation History (This Session Only)")
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
    print(f"\nSession Behavior:")
    print(f"  ✓ Conversation awareness: Within this session ONLY")
    print(f"  ✓ History saved to: {session.session_file}")
    print(f"  ✓ Starting a NEW chat will be completely independent\n")

except Exception as e:
    print(f"❌ Error during demo: {e}\n")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("Demo Complete!")
print("=" * 80)
print("\nConversation Awareness Explained:")
print("  ✓ Within ONE chat session: AI remembers all previous messages")
print("  ✓ Great for: Multi-turn Q&A, follow-up questions, context-dependent chats")
print("  ✓ Each NEW session starts fresh: No memory of previous chats")
print("  ✗ Previous chat history is NOT automatically loaded\n")
print("Try the interactive mode:")
print("  python unified_chat.py\n")
