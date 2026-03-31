#!/usr/bin/env python3
import sqlite3
import os

db_path = 'asset_cache.db'

# Check if file exists
if not os.path.exists(db_path):
    print(f"Error: Database file not found at {db_path}")
    exit(1)

# Connect to database
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get all table names
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()

print("✓ Database file exists")
print(f"✓ File size: {os.path.getsize(db_path)} bytes")
print("\n📋 Tables in database:")

if not tables:
    print("  (No tables found)")
else:
    for table in tables:
        table_name = table[0]
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        print(f"  - {table_name}: {count} records")
        
        # Show schema
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        if columns:
            col_names = ', '.join([col[1] for col in columns])
            print(f"    Columns: {col_names}")

conn.close()
print("\n✓ Database is healthy and ready to use!")
