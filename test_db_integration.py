#!/usr/bin/env python
"""
Test database integration with Ollama
"""

from dbchat import init_ollama, init_database, process_database_query

print("\n" + "=" * 80)
print(" Testing Ollama + Database Integration")
print("=" * 80 + "\n")

# Initialize database
print("[1] Initialize Database")
print("-" * 80)
if not init_database():
    print("❌ Database initialization failed")
    exit(1)

# Initialize Ollama
print("\n[2] Initialize Ollama")
print("-" * 80)
if not init_ollama():
    print("❌ Ollama initialization failed")
    exit(1)

# Test natural language query
print("\n[3] Test Natural Language Query Processing")
print("-" * 80)

test_query = "Show me all hardware products in the database"
print(f"\n📝 User Query: '{test_query}'")

result = process_database_query(test_query)

if result['success']:
    print(f"\n✓ Query successful!")
    print(f"\n📋 Ollama's Analysis:")
    print(result['response'][:200] + "..." if len(result['response']) > 200 else result['response'])
    
    if 'sql' in result:
        print(f"\n🔧 Generated SQL:")
        print(result['sql'])
    
    if result.get('results'):
        print(f"\n📊 Database Results:")
        print(result['formatted_results'])
    elif result.get('error'):
        print(f"\n⚠ {result['error']}")
else:
    print(f"\n❌ Query failed: {result['error']}")

print("\n" + "=" * 80)
print("✓ Database Integration Test Complete")
print("=" * 80)
print("\nTo use interactive mode: python dbchat.py\n")
