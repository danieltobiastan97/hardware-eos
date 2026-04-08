from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Date, JSON, func
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime, date
from pathlib import Path
import json

# ============= Date Parser Utility =============
def parse_date(date_input):
    """
    Convert string or date object to Python date object.
    
    Args:
        date_input: Can be a date object, datetime object, or ISO format string (YYYY-MM-DD)
    
    Returns:
        date object
        
    Raises:
        ValueError: If string format is invalid
    """
    if isinstance(date_input, datetime):
        # datetime is a subclass of date — check it FIRST or the branch below
        # will match and return the datetime unchanged.
        return date_input.date()

    if isinstance(date_input, date):
        # Already a plain date object
        return date_input
    
    if isinstance(date_input, str):
        # Parse ISO format string (YYYY-MM-DD)
        try:
            parsed = datetime.strptime(date_input, "%Y-%m-%d").date()
            return parsed
        except ValueError:
            raise ValueError(f"Invalid date format: '{date_input}'. Expected YYYY-MM-DD format.")
    
    raise TypeError(f"Date must be a date, datetime, or ISO format string. Got {type(date_input)}")

# Create a base class for all models to inherit from
Base = declarative_base()


class ProductEOS(Base):
    """Product End-of-Life/Support model with dynamic support tiers."""
    __tablename__ = 'product_eos'

    # column definitions
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    summary = Column(String, nullable=False)  # Text description
    hardware_software = Column(String(20), nullable=False)  # 'Hardware' or 'Software'
    support_model = Column(String(100), nullable=False)  # e.g., 'Version-Based'
    eos_date = Column(Date, nullable=False)  # End of Support Date
    source_urls = Column(JSON)  # Array of source URLs
    confidence = Column(Float, default=1.0)  # Confidence score (0-1)
    created_date = Column(DateTime, default=datetime.utcnow)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    support_tiers = relationship('SupportTier', backref='product', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<ProductEOS {self.name}>"
    
    def to_dict(self):
        """Convert to JSON-compatible dict."""
        return {
            'id': self.id,
            'Name': self.name,
            'Summary': self.summary,
            'Hardware/Software': self.hardware_software,
            'Support Model': self.support_model,
            'EOS Date': self.eos_date.isoformat(),
            'Support Tiers': [tier.to_dict() for tier in self.support_tiers],
            'Source URLs': self.source_urls or [],
            'Confidence': self.confidence
        }


class SupportTier(Base):
    """Dynamic support tier for products (one-to-many relationship)."""
    __tablename__ = 'support_tier'

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey('product_eos.id'), nullable=False)
    tier = Column(String(255), nullable=False)  # Tier name (e.g., 'End of SW Maintenance Releases')
    end_date = Column(Date, nullable=False)  # End date for this tier
    created_date = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<SupportTier {self.tier} - {self.end_date}>"
    
    def to_dict(self):
        """Convert to JSON-compatible dict."""
        return {
            'Tier': self.tier,
            'EndDate': self.end_date.isoformat()
        }
 
class assetCache(Base):
    """Legacy Asset Model to store the found hardware and software items."""
    __tablename__ = 'asset_cache'

    # column definitions
    id = Column(Integer, primary_key=True)
    item_name = Column(String(100), nullable=False, unique=True)
    item_type = Column(String(10), nullable=False)  # 'hardware' or 'software'
    processing_date = Column(DateTime, default=datetime.utcnow)
    result = Column(String)  # Stores the AI-generated JSON result as a string
    status = Column(String, default='success')  # success, failed, retry
    error_message = Column(String)
    processing_time = Column(Float)  # seconds

    def __repr__(self):
        return f"<AssetCache {self.item_name} ({self.status}) - {self.result}>"
    

def init_database(db_url="sqlite:///asset_cache.db"):
    """Initialize the database and return a session."""
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)  # Create tables based on the defined models
    Session = sessionmaker(bind=engine)
    return engine, Session()

# Database Operations
class AssetRepo:
    def __init__(self, session):
        self.session = session

    def add_entry(self, item_name, item_type, result, status='success', error_message=None, processing_time=0.0):
        """Add a new cache entry to the database."""
        entry = assetCache(
            item_name=item_name,
            item_type=item_type,
            result=result,
            status=status,
            error_message=error_message,
            processing_time=processing_time
        )
        self.session.add(entry)
        self.session.commit()
        return entry
    
    def get_entry_by_name(self, query_name):
        """Retrieve a cache entry by item name."""
        return self.session.query(assetCache).filter(assetCache.item_name.ilike(f"%{query_name}%")).first()
    
    def update_entry(self, entry_id, **kwargs):
        """Update an existing cache entry."""
        entry = self.session.query(assetCache).get(entry_id)
        if not entry:
            return None
        for key, value in kwargs.items():
            setattr(entry, key, value)
        self.session.commit()
        return entry
    
    def find_similar_entry(self, item_name):
        """Find an entry with a similar name (case-insensitive)."""
        return self.session.query(assetCache).filter(func.lower(assetCache.item_name) == item_name.lower()).first()


# Product EOS Repository
class ProductEOSRepo:
    """Repository for managing Product End-of-Support information."""
    
    def __init__(self, session):
        self.session = session

    def add_product(self, name, summary, hardware_software, support_model, eos_date, source_urls, confidence=1.0, created_timestamp=None):
        """Add a new product with EOS information.
        
        Args:
            eos_date: Can be a date object, datetime object, or ISO format string (YYYY-MM-DD)
            created_timestamp: Optional datetime object for when product was created (default: now UTC)
        """
        product = ProductEOS(
            name=name,
            summary=summary,
            hardware_software=hardware_software,
            support_model=support_model,
            eos_date=parse_date(eos_date),  # Convert to date object
            source_urls=source_urls,
            confidence=confidence,
            created_date=created_timestamp or datetime.utcnow()
        )
        self.session.add(product)
        self.session.commit()
        return product
    
    def add_support_tier(self, product_id, tier_name, end_date):
        """Add a support tier to a product (dynamic, can add many).
        
        Args:
            end_date: Can be a date object, datetime object, or ISO format string (YYYY-MM-DD)
        """
        support_tier = SupportTier(
            product_id=product_id,
            tier=tier_name,
            end_date=parse_date(end_date)  # Convert to date object
        )
        self.session.add(support_tier)
        self.session.commit()
        return support_tier
    
    def get_product_by_name(self, name):
        """Retrieve a product by name."""
        return self.session.query(ProductEOS).filter(ProductEOS.name.ilike(f"%{name}%")).first()
    
    def get_all_products(self):
        """Retrieve all products."""
        return self.session.query(ProductEOS).all()
    
    def get_product_tiers(self, product_id):
        """Get all support tiers for a product."""
        return self.session.query(SupportTier).filter(SupportTier.product_id == product_id).all()
    
    def update_product(self, product_id, **kwargs):
        """Update product information."""
        product = self.session.query(ProductEOS).get(product_id)
        if not product:
            return None
        for key, value in kwargs.items():
            if hasattr(product, key):
                setattr(product, key, value)
        self.session.commit()
        return product
    
    def delete_product(self, product_id):
        """Delete a product and all associated support tiers."""
        product = self.session.query(ProductEOS).get(product_id)
        if not product:
            return False
        self.session.delete(product)
        self.session.commit()
        return True
    
    def export_as_json(self, product_id):
        """Export product as JSON matching the required format."""
        product = self.session.query(ProductEOS).get(product_id)
        if not product:
            return None
        return product.to_dict()