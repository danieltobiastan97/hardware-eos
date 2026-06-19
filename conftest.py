"""
Pytest configuration and shared fixtures for hardware-eos-app tests.

This file is auto-discovered by pytest and provides:
- Environment setup
- Shared fixtures (database, Flask app)
- Test utilities
"""

import os
import sys
import csv
from pathlib import Path
import pytest

# ────────────────────────────────────────────────────────────────────────────
# Environment Setup (must run BEFORE webpage import)
# ────────────────────────────────────────────────────────────────────────────

os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-unit-tests-only")
os.environ.setdefault("APP_ADMIN_PASSWORD", "testpassword123")

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))


# ────────────────────────────────────────────────────────────────────────────
# Test Utilities
# ────────────────────────────────────────────────────────────────────────────

def make_csv(path, rows, headers=("Hardware", "Software")):
    """
    Write rows to a CSV file and return its string path.
    
    Args:
        path: Pathlib.Path or string path to CSV file
        rows: List of tuples representing data rows
        headers: Tuple of column headers (default: Hardware, Software)
    
    Returns:
        str: Path to the created CSV file
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    return str(path)


def make_excel(path, rows, sheet="Asset List", headers=("Hardware", "Software")):
    """
    Write rows to an Excel file and return its string path.
    
    Args:
        path: Pathlib.Path or string path to Excel file
        rows: List of tuples representing data rows
        sheet: Sheet name (default: Asset List)
        headers: Tuple of column headers
    
    Returns:
        str: Path to the created Excel file
    """
    import openpyxl
    
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    
    # Write headers
    ws.append(headers)
    
    # Write data rows
    for row in rows:
        ws.append(row)
    
    wb.save(path)
    return str(path)


# ────────────────────────────────────────────────────────────────────────────
# Pytest Fixtures
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def in_memory_db():
    """
    Isolated in-memory SQLite database for each test.
    
    Returns:
        Tuple[Engine, Session]: SQLAlchemy engine and session
    
    Example:
        def test_something(in_memory_db):
            engine, session = in_memory_db
            # Use session for database operations
    """
    from models import Base, init_database
    
    engine, session = init_database("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine, session
    session.close()


@pytest.fixture(scope="function")
def in_memory_repo(in_memory_db):
    """
    Isolated in-memory SQLite DB + ProductEOSRepo for each test.
    
    Returns:
        Tuple[ProductEOSRepo, Session]: Repository instance and session
    
    Example:
        def test_something(in_memory_repo):
            repo, session = in_memory_repo
            repo.add_product("Name", "Summary", ...)
    """
    from models import ProductEOSRepo
    
    engine, session = in_memory_db
    repo = ProductEOSRepo(session)
    yield repo, session


@pytest.fixture(scope="function")
def populated_db_session(in_memory_repo):
    """
    In-memory DB pre-seeded with sample products for RAG/retrieval tests.
    
    Returns:
        Session: SQLAlchemy session with test data
    
    Pre-populated products:
        - Windows Server 2019 (Software)
        - Cisco Catalyst 3750 (Hardware)
        - Dell PowerEdge R750 (Hardware)
        - Adobe Acrobat 2020 (Software)
    """
    repo, session = in_memory_repo
    
    # Populate with sample data
    repo.add_product(
        "Windows Server 2019", "Microsoft server OS", "Software",
        "Version-Based", "2029-01-09", ["https://microsoft.com/lifecycle"], 0.99
    )
    repo.add_product(
        "Cisco Catalyst 3750", "Cisco Gigabit switch EOS", "Hardware",
        "Fixed", "2024-10-29", ["https://cisco.com/lifecycle"], 0.95
    )
    repo.add_product(
        "Dell PowerEdge R750", "Dell 2U rack server", "Hardware",
        "Fixed", "2031-06-30", [], 0.90
    )
    repo.add_product(
        "Adobe Acrobat 2020", "Adobe PDF editor", "Software",
        "Version-Based", "2025-11-09", [], 0.95
    )
    
    yield session


@pytest.fixture(scope="function")
def flask_client():
    """
    Unauthenticated Flask test client (function-scoped for isolation).
    
    Returns:
        FlaskClient: Test client for making requests
    
    Usage:
        def test_login_page(flask_client):
            response = flask_client.get("/")
            assert response.status_code == 200
    """
    import webpage
    
    webpage.app.config["TESTING"] = True
    with webpage.app.test_client() as client:
        yield client


@pytest.fixture(scope="function")
def auth_client():
    """
    Authenticated Flask test client (auto-logged in as admin).
    
    Returns:
        FlaskClient: Authenticated test client
    
    Usage:
        def test_protected_route(auth_client):
            response = auth_client.get("/admin")
            assert response.status_code == 200
    """
    import webpage
    
    webpage.app.config["TESTING"] = True
    with webpage.app.test_client() as client:
        client.post("/login", data={
            "username": "admin",
            "password": "testpassword123"
        })
        yield client


@pytest.fixture(autouse=True)
def clear_caches():
    """
    Auto-clear in-memory caches between tests to prevent data leakage.
    
    This fixture runs automatically for every test without being explicitly
    requested. It clears caches that might persist between test runs.
    """
    yield
    
    # Clear any persistent caches here if needed
    # Example: global_cache.clear()


# ────────────────────────────────────────────────────────────────────────────
# Pytest Configuration & Hooks
# ────────────────────────────────────────────────────────────────────────────

def pytest_configure(config):
    """Pytest hook: runs before test collection."""
    # Add custom markers
    config.addinivalue_line(
        "markers", "security: mark test as a security/adversarial test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )


def pytest_collection_modifyitems(config, items):
    """Pytest hook: customize test collection."""
    for item in items:
        # Auto-mark Flask tests
        if "flask" in item.nodeid.lower():
            item.add_marker(pytest.mark.integration)
        
        # Auto-mark security tests
        if "break" in item.nodeid.lower() or "injection" in item.nodeid.lower():
            item.add_marker(pytest.mark.security)
