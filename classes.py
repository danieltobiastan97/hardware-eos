# helper.py
import json
import os
import pandas as pd
import datetime
import time

class Helper:
    def __init__(self):
        pass  # Initialize any required variables here

    def parse_llm_json(response_string):
        """
        Finds and parses a JSON object from a string, stripping any markdown fences.
        """
        try:
            # Find the first '{' and the last '}'
            start_index = response_string.find('{')
            end_index = response_string.rfind('}')

            if start_index != -1 and end_index != -1:
                # Slice the string to get only the JSON part
                json_only_string = response_string[start_index : end_index + 1]
                
                # Parse the clean string
                return json.loads(json_only_string)
            else:
                # Handle cases where no JSON object is found
                print("Error: Could not find a JSON object in the string.")
                return None
                
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")
            return None

    """
    Preprocesses the Excel or CSV file to extract hardware and software lists."""
    def preprocess(self, filename, sheet='Sheet1'):
        time_start = time.time()
        print(f'Starting Preprocessing for: {filename}...')
        
        try:
            # 1. Load the data — route by extension
            ext = os.path.splitext(filename)[1].lower()
            if ext == '.csv':
                df = pd.read_csv(filename)
            else:
                # engine='openpyxl' is often more reliable for modern .xlsx files
                df = pd.read_excel(filename, sheet_name=sheet)

            if df.empty:
                print(f"Warning: The sheet '{sheet}' is empty.")
                return [], []

            # 2. Optimized Cleaning Helper
            def clean_column(column_name):
                if column_name not in df.columns:
                    print(f"Warning: Column '{column_name}' not found in {sheet}.")
                    return []
                
                # Chain operations: drop nulls -> cast to string -> strip whitespace -> filter out empty strings
                return (
                    df[column_name]
                    .dropna()
                    .astype(str)
                    .str.strip()
                    .replace('', pd.NA) # Handle cells that were just spaces
                    .dropna()
                    .tolist()
                )

            # 3. Process Lists
            hw_list = clean_column('Hardware')
            sw_list = clean_column('Software')

            # 4. Remove Duplicates - Keep only unique items
            hw_list = list(dict.fromkeys(hw_list))  # Preserves order while removing duplicates
            sw_list = list(dict.fromkeys(sw_list))  # Preserves order while removing duplicates

            # 5. Success Reporting
            time_elapsed = time.time() - time_start
            print(f"Number of hardware items: {len(hw_list)}")
            print(f"Number of software items: {len(sw_list)}")
            print(f"Processing completed in {time_elapsed:.2f}s")
            print('-----------------------------------')
            
            return hw_list, sw_list

        except FileNotFoundError:
            print(f"Error: The file '{filename}' was not found.")
        except ValueError as e:
            print(f"Error: Sheet '{sheet}' not found, file is corrupted, or CSV is malformed. {e}")
        except PermissionError:
            print(f"Error: Permission denied. Is the file '{filename}' open in Excel?")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")

        # Return empty lists on any failure so the rest of your code doesn't crash
        return [], []

class Cleaner:
    def __init__(self):
        pass  # Initialize any required variables here

    def clean_text_to_unique(df_array) -> pd.Series: 
        """helper functions to convert to lower case and strip whitespace, drop na and nils"""
        df = df_array.str.lower().str.strip()
        # remvoe na or nilss
        lst = df.dropna()
        lst = lst[lst != 'nil']
        return lst.unique()

class Processing:
    def __init__(self):
        pass  # Initialize any required variables here

    def to_table(df_series):
        """
        Converts a Series of JSON objects to a DataFrame.
        """
        # Convert each JSON object in the Series to a DataFrame
        df = pd.DataFrame(df_series.tolist())
        return df
    
    def check_eos(row):
        if row['Time to EOS'] < 0:
            return "Yes"
        else:
            return "No"

    def return_eos(df):
        today = datetime.date.today()

        # Filter the DataFrame to include only rows where EOS is an actual date
        df['Filter EOS'] = pd.to_datetime(df['EOS Date'], format='%Y-%m-%d', errors='coerce')

        # catch non software or hardware
        clean_df = df[df['Hardware/Software'].isin(['Hardware', 'Software'])]
        df_exclude = df[df['Hardware/Software'].isin(['Hardware', 'Software']) == False]
        
        found_eos = clean_df[clean_df['Filter EOS'].notna()]
        unfound_eos = clean_df[clean_df['Filter EOS'].isna()]
        
        delta = (found_eos['Filter EOS'] - pd.Timestamp(today)).dt.days
        found_eos["Time to EOS"] = delta

        found_eos['EOS'] = found_eos.apply(Processing.check_eos, axis=1)

        return found_eos, unfound_eos, df_exclude
    
    def error_cache(results, eos_list):
        """
        Caches the results and eos_list for items that failed to process.
        """
        success, unsuccess = [], []
        for i, result in enumerate(results):
            if result is not None:
                success.append(result)
            else:
                unsuccess.append(eos_list[i])  # This mapping is always correct
        return success, unsuccess
    
    def processing_tiers(results):
        df = pd.DataFrame(results)

        # 2. Explode the 'Support Tiers' column to create separate rows
        #    Products with no tiers (like Chrome) will result in a row with NaN
        df_exploded = df.explode('Support Tiers').reset_index(drop=True)

        # 3. Normalize the 'Support Tiers' column (which now contains dictionaries)
        #    and join it back to the main data
        tiers_df = pd.json_normalize(df_exploded['Support Tiers'])
        final_df = df_exploded.drop(columns=['Support Tiers']).join(tiers_df)

        # Optional: Convert date strings to datetime objects for calculations
        final_df['EOS Date'] = pd.to_datetime(final_df['EOS Date'])
        final_df['EndDate'] = pd.to_datetime(final_df['EndDate'])
        return final_df
        