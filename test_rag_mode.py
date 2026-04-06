#!/usr/bin/env python
"""
Test RAG implementation - database retrieval + Ollama answering
"""

from dbchat import init_database, init_ollama, process_database_query

print("\n" + "=" * 80)
print(" Testing RAG Implementation (Retrieval-Augmented Generation)")
print("=" * 80 + "\n")

if not init_database():
    print("❌ Database initialization failed")
    exit(1)

if not init_ollama():
    print("❌ Ollama initialization failed")
    exit(1)

# Test queries
test_queries = [
    "Show me all software products",
    "What hardware is ending support in 2026?",
    "Which products are expiring soon?",
]

print("[Testing RAG Queries]\n")

for i, query in enumerate(test_queries, 1):
    print(f"Test {i}: '{query}'")
    print("-" * 80)
    
    result = process_database_query(query)
    
    if result['success']:
        print(f"✓ Success")
        print(f"\n🤖 Ollama's Answer:")
        print(result['response'][:300] + "..." if len(result['response']) > 300 else result['response'])
    else:
        print(f"✗ Error: {result['error']}")
    
    print()

print("=" * 80)
print("✓ RAG Implementation Testing Complete")
print("=" * 80)
print("\nKey differences from SQL generation:")
print("  - No SQL displayed to user")
print("  - Database retrieval happens automatically")
print("  - Ollama answers based on provided context")
print("  - Natural language responses (not raw data)\n")
