# helper.py
import json
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
        
    def preprocess(filename, sheet):
        time_start = time.time()
        print('Starting Preprocessing...')
        try:
            asset_list = pd.read_excel(filename, sheet_name = sheet)
            asset_list.rename(columns={asset_list.columns[3]: 'Software Version'}, inplace=True)
            asset_list['Software Version'] = asset_list['Software Version'].str.strip()
            time_end = time.time() - time_start
            print(f'Asset list read in {time_end:.1f}s')
            print('-----------------------------------')
            return asset_list
        

        except FileNotFoundError:
            print(f"Error: The file '{filename}' was not found.")
            return None # Return None to indicate failure

        except (ValueError, KeyError, IndexError) as e:
            # Catches bad sheet names, column rename/access issues
            print(f"Error processing the sheet '{sheet}' in '{filename}': {e}")
            return None # Return None to indicate failure

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
        