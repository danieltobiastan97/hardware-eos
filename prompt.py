import json
import os
from pathlib import Path
from google.genai import types
from google import genai
from classes import Helper, Cleaner, Processing
import time
import asyncio
import pandas as pd
import numpy as np
import sys
from threading import Thread

# Get absolute path to script directory for file paths
SCRIPT_DIR = Path(__file__).resolve().parent

# Spinner class for terminal animation
class Spinner:
    def __init__(self, message="Loading"):
        self.message = message
        self.spinner_chars = ['|', '/', '-', '\\']
        self.index = 0
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = Thread(target=self._spin, daemon=True)
        self.thread.start()

    def _spin(self):
        while self.running:
            sys.stdout.write(f'\r{self.message} {self.spinner_chars[self.index % len(self.spinner_chars)]}   ')
            sys.stdout.flush()
            self.index += 1
            time.sleep(0.15)

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()
        sys.stdout.write(f'\r{self.message} ✓\n')
        sys.stdout.flush()

# load the API keys
def keys_and_prompt_setup(path='keys.json', prompt_path='prompts/prompt.txt'):
    """Load API keys and prompt from files using absolute paths."""
    # Convert to absolute paths if relative
    key_path = Path(path) if Path(path).is_absolute() else SCRIPT_DIR / path
    prompt_file_path = Path(prompt_path) if Path(prompt_path).is_absolute() else SCRIPT_DIR / prompt_path
    
    try:
        with open(key_path, 'r') as file:
            keys = json.load(file)
    except FileNotFoundError:
        # On Cloud Run, keys.json is not present — fall back to environment variables.
        env_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not env_api_key:
            raise FileNotFoundError(
                f"API keys file not found ({key_path}) and GEMINI_API_KEY env var is not set."
            )
        keys = {"GEMINI_API_KEY": env_api_key}

    # load the prompt from a different text file
    try:
        with open(prompt_file_path, 'r') as pmt_file:
            instruct = pmt_file.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"Prompt file not found: {prompt_file_path}")
    
    return keys, instruct

def client_setup(keys):
    """
    Initialize Gemini client for pipeline processing.
    Raises an error if API key is missing or invalid.
    """
    try:
        # Check if API key exists
        if 'GEMINI_API_KEY' not in keys or not keys['GEMINI_API_KEY']:
            raise ValueError("GEMINI_API_KEY is missing or empty. Please check your keys.json file.")
        
        # Initialize client
        client = genai.Client(api_key=keys['GEMINI_API_KEY'])
        print('✓ Pipeline client successfully established.')
        
        # Set up configuration
        thinking_setup = types.ThinkingConfig(
            thinking_level="low"  # Options: "minimal", "low", "medium", "high"
        )
        scraper_client = types.Tool(google_search=types.GoogleSearch())
        config = types.GenerateContentConfig(
            thinking_config=thinking_setup,
            tools=[scraper_client],
            temperature=0.0, 
            response_mime_type="application/json", 
        )
        return client, config
        
    except ValueError as ve:
        error_msg = f"❌ API Key Error: {str(ve)}"
        print(error_msg)
        raise RuntimeError(error_msg)
    except Exception as e:
        error_msg = f"❌ Failed to initialize Gemini client for pipeline. Please check your API key in keys.json or environment variables. Error: {str(e)}"
        print(error_msg)
        raise RuntimeError(error_msg)

def chat_client_setup(keys):
    """
    Initialize Gemini client for chat feature.
    Raises an error if API key is missing or invalid.
    """
    try:
        # Check if API key exists
        if 'GEMINI_API_KEY' not in keys or not keys['GEMINI_API_KEY']:
            raise ValueError("GEMINI_API_KEY is missing or empty. Please check your keys.json file.")
        
        # Initialize client
        client = genai.Client(api_key=keys['GEMINI_API_KEY'])
        print('✓ Chat client successfully established.')
        
        # Set up configuration
        thinking_setup = types.ThinkingConfig(
            thinking_level="low"  # Options: "minimal", "low", "medium", "high"
        )
        scraper_client = types.Tool(google_search=types.GoogleSearch())
        config = types.GenerateContentConfig(
            thinking_config=thinking_setup,
            tools=[scraper_client]
        )
        return client, config
        
    except ValueError as ve:
        error_msg = f"❌ API Key Error: {str(ve)}"
        print(error_msg)
        raise RuntimeError(error_msg)
    except Exception as e:
        error_msg = f"❌ Failed to initialize Gemini client for chat. Please check your API key in keys.json or environment variables. Error: {str(e)}"
        print(error_msg)
        raise RuntimeError(error_msg)

async def process_line(string, client, config, instruct):
    print(f"Processing item: {string}")
    # Check for injection attempts
    Helper.detect_injection_attempt(string)

    # Sanitize input and limit to 150 characters for product names
    sanitized_input = Helper.sanitize_asset_name(string[:150])
    safety_input = f'<asset_name>{sanitized_input}</asset_name>'
    content = instruct + "\n\nProcess this asset: " + safety_input

    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=content,
        config=config
    )

    # Validate response has content before accessing
    if not response or not response.candidates or not response.candidates[0].content.parts:
        raise RuntimeError("Gemini returned an empty response.")

    json_response = ""
    for part in response.candidates[0].content.parts:
        if part.text:
            json_response += part.text

    if not json_response.strip():
        raise RuntimeError("Gemini response contained no text parts.")

    # Parse JSON response
    parsed_response = Helper.parse_llm_json(json_response)
    if parsed_response is None:
        raise RuntimeError("Gemini response could not be parsed as JSON.")

    # Validate response structure and constraints
    if not Helper.validate_eos_response(parsed_response):
        raise RuntimeError("Gemini response failed EOS schema validation.")

    return parsed_response

async def ai_main(eos_list, instruct, client, config):
    tasks = [process_line(item, client, config, instruct) for item in eos_list]
    results = await asyncio.gather(*tasks)

    # error caching for failed API calls or bad responses
    success, unsuccess = Processing.error_cache(results, eos_list)

    print(f"Successfully processed {len(success)} items.")
    
    # Add a retry limit if needed
    retry_limit = 3
    retry_count = 0

    while unsuccess and retry_count < retry_limit:
        print(f"Retrying {len(unsuccess)} items...")
        retry_tasks = [process_line(item, client, config, instruct) for item in unsuccess]
        retry_results = await asyncio.gather(*retry_tasks)
        retry_success, unsuccess = Processing.error_cache(retry_results, unsuccess)
        
        # add to main success list
        success.extend(retry_success)

        retry_count += 1
        if unsuccess:
            print(f"Retry {retry_count} failed for {len(unsuccess)} items.")
    
    return success, unsuccess

async def run_async(lst, instruct, client, config):
    spinner = Spinner(f"Processing {len(lst)} items")
    spinner.start()
    
    # add time start
    start_time = time.time()
    results, failed_items = await ai_main(lst, instruct, client, config)
    
    spinner.stop()
    
    # add time end
    elapsed = time.time() - start_time  # Calculate elapsed time
    print(f"Time taken: {elapsed:.2f} seconds")  # Print elapsed time
    print("Async processing completed.")
    return results, failed_items 

# Run the async function, change this for the script. 

def main():
    """Interactive CLI test interface for EOS asset processing."""
    print("\n" + "="*80)
    print("  ASSET EOS/EOL LOOKUP — INTERACTIVE CLI TEST INTERFACE")
    print("="*80 + "\n")
    
    # Setup phase
    print("📋 Initializing system...")
    try:
        keys, instruct = keys_and_prompt_setup()
        print("✓ Keys and prompt successfully loaded.")
        
        client, config = client_setup(keys)
        print("✓ Client setup successfully completed.\n")
    except Exception as e:
        print(f"❌ Setup failed: {e}")
        return
    
    # Main CLI loop
    while True:
        print("-" * 80)
        print("INPUT FORMAT: Enter asset names separated by semicolons")
        print("EXAMPLE: Dell PowerEdge R750; Windows Server 2019; Cisco Catalyst 3750")
        print("COMMANDS: 'exit' or 'quit' to terminate")
        print("-" * 80 + "\n")
        
        try:
            user_input = input("🔍 Enter asset names (semicolon-separated): ").strip()
            
            # Check for exit command
            if user_input.lower() in ['exit', 'quit', 'q']:
                print("\n✓ Exiting CLI. Goodbye!\n")
                break
            
            # Validate input
            if not user_input:
                print("⚠️  Empty input. Please enter at least one asset name.\n")
                continue
            
            # Parse assets
            assets = [asset.strip() for asset in user_input.split(';')]
            assets = [a for a in assets if a]  # Remove empty strings
            
            if not assets:
                print("⚠️  No valid assets found. Please try again.\n")
                continue
            
            print(f"\n📊 Processing {len(assets)} asset(s)...\n")
            
            # Process assets
            spinner = Spinner(f"Processing {len(assets)} asset")
            spinner.start()
            
            try:
                results, failed = asyncio.run(run_async(assets, instruct, client, config))
                spinner.stop()
                
                # Display results
                print("\n" + "="*80)
                print(f"  RESULTS: {len(results)} Successful | {len(failed)} Failed")
                print("="*80 + "\n")
                
                if results:
                    print("✓ SUCCESSFUL RESULTS:")
                    print("-" * 80)
                    for i, result in enumerate(results, 1):
                        if isinstance(result, dict):
                            print(f"\n[{i}] {result.get('Name', 'Unknown')}")
                            print(f"    Type: {result.get('Hardware/Software', 'N/A')}")
                            print(f"    EOS Date: {result.get('EOS Date', 'N/A')}")
                            print(f"    Confidence: {result.get('Confidence', 0.0)}")
                            print(f"    Support Model: {result.get('Support Model', 'N/A')}")
                            print(f"    Summary: {result.get('Summary', 'N/A')[:100]}...")
                            urls = result.get('Source URLs', [])
                            if urls:
                                print(f"    Sources: {', '.join(urls[:2])}")
                        else:
                            print(f"\n[{i}] {result}")
                    print("\n" + "-" * 80)
                
                if failed:
                    print(f"\n❌ FAILED ITEMS: {len(failed)}")
                    print("-" * 80)
                    for item in failed:
                        print(f"  • {item}")
                    print("-" * 80)
                
                print(f"\n📈 Summary: {len(results)}/{len(assets)} processed successfully\n")
                
            except Exception as e:
                spinner.stop()
                print(f"\n❌ Processing error: {e}\n")
        
        except KeyboardInterrupt:
            print("\n\n⚠️  Interrupted by user. Exiting...\n")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}\n")

if __name__ == '__main__':
    main()

