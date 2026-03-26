#!/usr/bin/env python
"""Script to initialize the SQLite database for Hardware EOS tracker."""
import os
from flask import Flask
from models import db, UploadedAsset, CacheEntry

if __name__ == '__main__':
    # Create a simple Flask app for initialization
    init_app = Flask(__name__)
    
    # Configure database path
    db_path = os.path.join(os.path.dirname(__file__), 'hardware_eos.db')
    init_app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    init_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Initialize SQLAlchemy with app
    db.init_app(init_app)
    
    # Create tables within app context
    with init_app.app_context():
        db.create_all()
        print(f"✓ Database created successfully at: {db_path}")
