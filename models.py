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
    systems = relationship('System', secondary='product_system', backref='products')

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
            'Confidence': self.confidence,
            'Systems': [{'id': s.id, 'name': s.name} for s in self.systems]
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


class System(Base):
    """Project/Application system for organizing assets."""
    __tablename__ = 'system'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    created_date = Column(DateTime, default=datetime.utcnow)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<System {self.name}>"
    
    def to_dict(self):
        """Convert to JSON-compatible dict."""
        return {
            'id': self.id,
            'name': self.name,
            'created_date': self.created_date.isoformat(),
            'updated_date': self.updated_date.isoformat(),
            'asset_count': len(self.products)
        }


class ProductSystem(Base):
    """Junction table for many-to-many relationship between products and systems."""
    __tablename__ = 'product_system'

    product_id = Column(Integer, ForeignKey('product_eos.id'), primary_key=True)
    system_id = Column(Integer, ForeignKey('system.id'), primary_key=True)
    created_date = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<ProductSystem product_id={self.product_id}, system_id={self.system_id}>"
 
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
    
    # System Management Methods
    def create_system(self, name):
        """Create a new system."""
        existing = self.session.query(System).filter(func.lower(System.name) == name.lower()).first()
        if existing:
            return existing  # Return existing system if already exists
        system = System(name=name)
        self.session.add(system)
        self.session.commit()
        return system
    
    def get_system_by_name(self, name):
        """Retrieve a system by name."""
        return self.session.query(System).filter(func.lower(System.name) == name.lower()).first()
    
    def get_system_by_id(self, system_id):
        """Retrieve a system by ID."""
        return self.session.query(System).get(system_id)
    
    def get_all_systems(self):
        """Retrieve all systems with asset counts."""
        systems = self.session.query(System).all()
        return [{
            'id': s.id,
            'name': s.name,
            'asset_count': len(s.products),
            'created_date': s.created_date.isoformat(),
            'updated_date': s.updated_date.isoformat()
        } for s in systems]
    
    def add_system_to_product(self, product_id, system_id):
        """Associate a system with a product."""
        product = self.session.query(ProductEOS).get(product_id)
        system = self.session.query(System).get(system_id)
        
        if not product or not system:
            return False
        
        # Check if already associated
        existing = self.session.query(ProductSystem).filter(
            ProductSystem.product_id == product_id,
            ProductSystem.system_id == system_id
        ).first()
        
        if existing:
            return True  # Already associated
        
        association = ProductSystem(product_id=product_id, system_id=system_id)
        self.session.add(association)
        self.session.commit()
        return True
    
    def remove_system_from_product(self, product_id, system_id):
        """Remove a system from a product."""
        association = self.session.query(ProductSystem).filter(
            ProductSystem.product_id == product_id,
            ProductSystem.system_id == system_id
        ).first()
        
        if not association:
            return False
        
        self.session.delete(association)
        self.session.commit()
        return True
    
    def get_systems_by_product(self, product_id):
        """Get all systems associated with a product."""
        product = self.session.query(ProductEOS).get(product_id)
        if not product:
            return []
        return [{
            'id': s.id,
            'name': s.name
        } for s in product.systems]
    
    def get_products_by_systems(self, system_ids):
        """Get all products associated with any of the given systems (OR logic)."""
        if not system_ids:
            return []
        
        products = self.session.query(ProductEOS).join(
            ProductSystem
        ).filter(
            ProductSystem.system_id.in_(system_ids)
        ).distinct().all()
        
        return products

    def update_system(self, system_id, new_name):
        """Rename an existing system. Returns system, False if not found, None if name conflict."""
        system = self.session.query(System).get(system_id)
        if not system:
            return False

        normalized = (new_name or '').strip()
        if not normalized:
            return None

        existing = self.session.query(System).filter(
            func.lower(System.name) == normalized.lower(),
            System.id != system_id
        ).first()
        if existing:
            return None

        system.name = normalized
        self.session.commit()
        return system
    
    def delete_system(self, system_id):
        """Delete a system and all associations."""
        system = self.session.query(System).get(system_id)
        if not system:
            return False
        
        # Delete all associations
        self.session.query(ProductSystem).filter(ProductSystem.system_id == system_id).delete()
        self.session.delete(system)
        self.session.commit()
        return True