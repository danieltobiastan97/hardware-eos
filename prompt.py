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
        raise FileNotFoundError(f"API keys file not found: {key_path}")

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
    try:
        await asyncio.sleep(2)  # Sleep to avoid hitting rate limits
        response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=instruct + ' ' + string,
        config=config
    )
        json_response = ""
        # Validate response has content before accessing
        if not response or not response.candidates or not response.candidates[0].content.parts:
            print(f"Error: Empty or invalid response for {string}")
            return None
        for part in response.candidates[0].content.parts:
            if part.text:
                json_response += part.text
        return Helper.parse_llm_json(json_response) # includes throwing none in here as well
    except Exception as e:
        print(f"Error processing {string}: {e}")
        return None # need to add some handling here to log if needed. 

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
    # start the client setup and preprocessing
    keys, instruct = keys_and_prompt_setup()
    print("Keys and prompt successfully loaded.")
    client, config = client_setup(keys) # you can insert your own keys
    print("Client setup successfully completed.")
    
    # start the reading in of data with spinner
    spinner = Spinner("Reading file")
    spinner.start()
    processor = Helper()
    hw_list, sw_list = processor.preprocess('test.xlsx', sheet='Asset List')
    spinner.stop()

    # show sw
    print(f"SW List: {sw_list}")

    # async processing of the hardware list
    hw_results, hw_failed_items = asyncio.run(run_async(hw_list[:2], instruct, client, config))
    # async processing of software list
    sw_results, sw_failed_items = asyncio.run(run_async(sw_list[:2], instruct, client, config))

    #print(f"Failed items: {failed_items}")
    ##print(f"Successful items: {len(results)}")
    return hw_results, sw_results

if __name__ == '__main__':
    main()

