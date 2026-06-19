#!/usr/bin/env python3
"""
Test script to verify Google Gemini API connectivity
"""
import json
from pathlib import Path
from google.genai import types
from google import genai
import asyncio

SCRIPT_DIR = Path(__file__).resolve().parent

def test_api():
    print("🔍 Testing Google Gemini API Connection...\n")
    
    # Step 1: Load API key
    print("1️⃣  Loading API key from keys.json...")
    try:
        with open(SCRIPT_DIR / 'keys.json', 'r') as f:
            keys = json.load(f)
        api_key = keys.get('GEMINI_API_KEY', '')
        
        if not api_key:
            print("❌ ERROR: GEMINI_API_KEY is empty in keys.json")
            return False
        
        print(f"✓ API Key loaded: {api_key[:20]}...")
    except FileNotFoundError:
        print("❌ ERROR: keys.json not found")
        return False
    except Exception as e:
        print(f"❌ ERROR loading keys.json: {e}")
        return False
    
    # Step 2: Initialize client
    print("\n2️⃣  Initializing Gemini client...")
    try:
        client = genai.Client(api_key=api_key)
        print("✓ Client initialized successfully")
    except Exception as e:
        print(f"❌ ERROR initializing client: {e}")
        return False
    
    # Step 3: Set up config
    print("\n3️⃣  Setting up configuration...")
    try:
        thinking_setup = types.ThinkingConfig(thinking_level="low")
        scraper_client = types.Tool(google_search=types.GoogleSearch())
        config = types.GenerateContentConfig(
            thinking_config=thinking_setup,
            tools=[scraper_client],
            temperature=0.0,
            response_mime_type="application/json",
        )
        print("✓ Configuration set up successfully")
    except Exception as e:
        print(f"❌ ERROR setting up config: {e}")
        return False
    
    # Step 4: Test API call
    print("\n4️⃣  Making test API call...")
    try:
        test_prompt = 'Return {"status": "ok", "message": "API is working"} in JSON format.'
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=test_prompt,
            config=config
        )
        
        print(f"✓ API call successful!")
        print(f"   Response type: {type(response)}")
        print(f"   Has candidates: {bool(response.candidates if response else None)}")
        
        if response and response.candidates:
            print(f"   First candidate: {response.candidates[0]}")
            if response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'text'):
                        print(f"   Response text: {part.text[:200]}")
        
        return True
        
    except Exception as e:
        print(f"❌ ERROR during API call: {e}")
        import traceback
        print(f"\nFull traceback:\n{traceback.format_exc()}")
        return False

if __name__ == "__main__":
    success = test_api()
    print("\n" + "="*50)
    if success:
        print("✅ API TEST PASSED - Google API is working!")
    else:
        print("❌ API TEST FAILED - Check errors above")
