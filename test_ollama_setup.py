#!/usr/bin/env python
"""
Test script for Ollama database chat environment setup.
Verifies connection and shows sample output without requiring interaction.
"""

from dbchat import init_ollama, query_ollama, get_available_models

print("\n" + "=" * 80)
print(" Testing Ollama Database Chat Environment")
print("=" * 80 + "\n")

# Test 1: Initialize Ollama
print("[TEST 1] Initialize Ollama Environment (using fastest available model)")
print("-" * 80)
if init_ollama():
    print("✓ Initialization successful\n")
else:
    print("❌ Initialization failed\n")
    print("Make sure Ollama is running: ollama serve")
    exit(1)

# Test 2: Show available models
print("[TEST 2] List Available Models")
print("-" * 80)
models = get_available_models()
if models:
    for i, model in enumerate(models, 1):
        print(f"  {i}. {model}")
    print()
else:
    print("  No models found\n")

# Test 3: Send a single sample query
print("[TEST 3] Test Natural Language Query Processing")
print("-" * 80)

# Single test query to demonstrate functionality
test_query = "A user asks: 'Show me all products from 2025 that are end-of-life'. How would you interpret this database request?"

print(f"\n[Sample Query] User Input:")
print(f"  '{test_query}'")

print("\n⏳ Processing with Ollama (please wait, first inference may be slow)...")
result = query_ollama(test_query)

if result['success']:
    print(f"\n✓ Query processed successfully!")
    print(f"\n[Sample Query] Ollama Response:")
    print(f"\n{result['response']}\n")
else:
    print(f"\n❌ Query failed: {result['error']}\n")
    print("Note: First model inference can be slow (1-2 minutes depending on model size).")
    print("For faster responses, consider using a smaller model like 'llama3.2' or 'gemma3:1b'")

print("=" * 80)
print("✓ Environment Test Complete")
print("=" * 80)
print("\nTo use interactive mode, run: python dbchat.py\n")

