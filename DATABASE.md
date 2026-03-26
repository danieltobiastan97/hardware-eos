# SQLite Database Setup

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Initialize the database
```bash
python db_init.py
```

This creates `hardware_eos.db` in the project root with two tables:
- **uploaded_assets**: Tracks file uploads and metadata
- **cache_entries**: Stores AI processing results to avoid re-processing

### 3. Database Integration in Flask (Optional)

To integrate with your Flask app, update `webpage.py`:

```python
from models import db, init_db, UploadedAsset, CacheEntry

# After creating Flask app
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///hardware_eos.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# Initialize on app start
with app.app_context():
    db.create_all()
```

## Schema Overview

### UploadedAsset Table
- `id`: Unique identifier
- `filename`: Stored filename
- `original_filename`: Original uploaded filename
- `file_type`: File extension (xlsx, csv, etc.)
- `file_size`: Size in bytes
- `upload_date`: Timestamp
- `hw_count`: Number of hardware items
- `sw_count`: Number of software items
- `processing_status`: pending, processing, completed, failed
- `error_message`: Error details if failed

### CacheEntry Table
- `id`: Unique identifier
- `asset_id`: Foreign key to UploadedAsset
- `item_name`: Name of processed item (indexed for fast lookup)
- `item_type`: "hardware" or "software"
- `processing_date`: Timestamp
- `result`: JSON result from AI model
- `status`: success, failed, retry
- `error_message`: Error details
- `processing_time`: Seconds taken to process

## Example Usage

### Save an upload
```python
asset = UploadedAsset(
    filename='20250325_001.xlsx',
    original_filename='test.xlsx',
    file_type='xlsx',
    file_size=15234,
    hw_count=5,
    sw_count=3,
    processing_status='completed'
)
db.session.add(asset)
db.session.commit()
```

### Cache a result
```python
cache = CacheEntry(
    asset_id=1,
    item_name='Dell XPS 13',
    item_type='hardware',
    result={'category': 'Laptop', 'specs': {...}},
    status='success',
    processing_time=2.3
)
db.session.add(cache)
db.session.commit()
```

### Query cache
```python
result = CacheEntry.query.filter_by(item_name='Dell XPS 13').first()
if result:
    print(result.result)  # Retrieve cached AI result
```

## Migration Notes

- Database file is not committed to git (add `*.db` to `.gitignore`)
- Cache reduces API calls and speeds up re-processing
- Use `asset_id` to associate cache entries with file uploads
