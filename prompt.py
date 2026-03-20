import json
import os
from google.genai import types
from google import genai
from classes import Helper, Cleaner, Processing
import time
import asyncio
import pandas as pd

# load the API keys
with open('keys.json', 'r') as file:
    keys = json.load(file)

# load the prompt from a different text file
with open('prompt.txt', 'r') as pmt_file:
    instruct = pmt_file.read()

def client_setup(): # need to include some try except error handling here
    client = genai.Client(api_key=keys['GEMINI_API_KEY'])
    print('Client successfully established.')

    # Set up the google search tool for the client.
    scraper_client = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(
        tools=[scraper_client],
        thinking_config=types.ThinkingConfig(thinking_budget=-1),
        temperature = 0.2,
)
    return client, config

client, config = client_setup()

async def process_line(string, client, config):
    print(f"Processing item: {string}")
    try:
        await asyncio.sleep(1)  # Sleep to avoid hitting rate limits
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=instruct + ' ' + string,
            config=config
        )
        return Helper.parse_llm_json(response.text) # includes throwing none in here as well
    except Exception as e:
        print(f"Error processing {string}: {e}")
        return None # need to add some handling here to log if needed. 

async def main(eos_list):
    client, config = client_setup()
    tasks = [process_line(item, client, config) for item in eos_list]
    results = await asyncio.gather(*tasks)

    # error caching for failed API calls or bad responses
    success, unsuccess = Processing.error_cache(results, eos_list)

    print(f"Successfully processed {len(success)} items.")
    
    # Add a retry limit if needed
    retry_limit = 3
    retry_count = 0

    while unsuccess and retry_count < retry_limit:
        print(f"Retrying {len(unsuccess)} items...")
        retry_tasks = [process_line(item, client, config) for item in unsuccess]
        retry_results = await asyncio.gather(*retry_tasks)
        retry_success, unsuccess = Processing.error_cache(retry_results, unsuccess)
        
        # add to main success list
        success.extend(retry_success)

        retry_count += 1
        if unsuccess:
            print(f"Retry {retry_count} failed for {len(unsuccess)} items.")
    
    return success, unsuccess

async def run_async(lst):
    print("Starting async processing...")
    # add time start
    start_time = time.time()
    results, failed_items = await main(lst)
    # add time end
    elapsed = time.time() - start_time  # Calculate elapsed time
    print(f"Time taken: {elapsed:.2f} seconds")  # Print elapsed time
    print("Async processing completed.")
    return results, failed_items 

# Run the async function, change this for the script. 

print('-----------------------------------')
asset_list = Helper.preprocess('SWandHW.xlsx', sheet = 'Sheet1')

omnii_sw = Cleaner.clean_text_to_unique(asset_list["Software Version"])
print('Identified the Software')
print('-----------------------------------')
results, failed_items = asyncio.run(run_async(asset_list))

# Post-processing the results
