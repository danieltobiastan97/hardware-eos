#!/usr/bin/env python
"""
Test improved Ollama configuration with lower temperature and better prompts
"""

from dbchat import init_database, init_ollama, process_database_query

print("\n" + "=" * 80)
print(" Testing Improved Ollama Configuration")
print(" (Lower Temperature: 0.2 + Enhanced System Prompt + Thinking)")
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
    "Find hardware items with EOS date in 2026",
    "What products are ending support before 2025?",
]

print("[Testing Query Quality Improvements]\n")

for i, query in enumerate(test_queries, 1):
    print(f"Test {i}: '{query}'")
    print("-" * 80)
    
    result = process_database_query(query)
    
    if result['success']:
        print(f"✓ Success")
        if 'sql' in result:
            print(f"  SQL: {result['sql']}")
        print(f"  Results: {result['row_count']} rows")
        if result['results']:
            print(f"  Sample: {result['results'][0].get('name', 'N/A')}")
    else:
        print(f"✗ Error: {result['error']}")
    
    print()

print("=" * 80)
print("✓ Improved Configuration Testing Complete")
print("=" * 80)
