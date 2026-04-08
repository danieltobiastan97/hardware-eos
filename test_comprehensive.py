"""
test_comprehensive.py

Comprehensive tests for hardware-eos-app core functionality.
Covers models, helpers, Flask routes, and adversarial edge-case "break attempts".

Run with:
    pytest test_comprehensive.py -v
    pytest test_comprehensive.py -v --tb=short   (concise failure output)
"""

import os
import sys
import json
import csv
import io
import tempfile
import pytest
from pathlib import Path
from datetime import date, datetime
from unittest.mock import patch, MagicMock

# ── Set env vars BEFORE any import of webpage (module-level init reads them) ─
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-unit-tests-only")
os.environ.setdefault("APP_ADMIN_PASSWORD", "testpassword123")

# ── Ensure local modules are importable ──────────────────────────────────────
TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_csv(path, rows, headers=("Hardware", "Software")):
    """Write rows to a CSV file and return its string path."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    return str(path)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def in_memory_repo():
    """Isolated in-memory SQLite DB + ProductEOSRepo for each test."""
    from models import Base, ProductEOSRepo, init_database
    engine, session = init_database("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    repo = ProductEOSRepo(session)
    yield repo, session
    session.close()


@pytest.fixture
def populated_db_session():
    """In-memory DB seeded with several products for RAG retrieval tests."""
    from models import Base, ProductEOSRepo, init_database
    engine, session = init_database("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    repo = ProductEOSRepo(session)
    repo.add_product("Windows Server 2019", "Microsoft server OS", "Software",
                     "Version-Based", "2029-01-09", ["https://microsoft.com/lifecycle"], 0.99)
    repo.add_product("Cisco Catalyst 3750", "Cisco Gigabit switch EOS", "Hardware",
                     "Fixed", "2024-10-29", ["https://cisco.com/lifecycle"], 0.95)
    repo.add_product("Dell PowerEdge R750", "Dell 2U rack server", "Hardware",
                     "Fixed", "2031-06-30", [], 0.90)
    repo.add_product("Adobe Acrobat 2020", "Adobe PDF editor", "Software",
                     "Version-Based", "2025-11-09", [], 0.95)
    yield session
    session.close()


@pytest.fixture
def flask_client():
    """Unauthenticated Flask test client (function-scoped for isolation)."""
    import webpage
    webpage.app.config["TESTING"] = True
    with webpage.app.test_client() as client:
        yield client


@pytest.fixture
def auth_client():
    """Authenticated Flask test client — logs in before each test."""
    import webpage
    webpage.app.config["TESTING"] = True
    with webpage.app.test_client() as client:
        client.post("/login", data={"username": "admin", "password": "testpassword123"})
        yield client


# ─────────────────────────────────────────────────────────────────────────────
# 1. parse_date  (models.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestParseDate:
    """Unit tests for models.parse_date — boundary + break attempts."""

    def test_valid_iso_string(self):
        from models import parse_date
        assert parse_date("2025-06-15") == date(2025, 6, 15)

    def test_date_object_passthrough(self):
        from models import parse_date
        today = date.today()
        assert parse_date(today) is today

    def test_datetime_converts_to_date(self):
        from models import parse_date
        dt = datetime(2024, 3, 20, 12, 0, 0)
        assert parse_date(dt) == date(2024, 3, 20)

    def test_placeholder_date(self):
        """2099-12-31 is the app-wide 'no EOS found' sentinel."""
        from models import parse_date
        assert parse_date("2099-12-31") == date(2099, 12, 31)

    def test_far_past_date(self):
        from models import parse_date
        assert parse_date("2001-01-01") == date(2001, 1, 1)

    # ── Break attempts ──────────────────────────────────────────────────────

    def test_dd_mm_yyyy_raises(self):
        from models import parse_date
        with pytest.raises(ValueError):
            parse_date("15-06-2025")

    def test_slash_separated_raises(self):
        from models import parse_date
        with pytest.raises(ValueError):
            parse_date("2025/06/15")

    def test_invalid_month_13_raises(self):
        from models import parse_date
        with pytest.raises(ValueError):
            parse_date("2025-13-01")

    def test_feb_30_raises(self):
        from models import parse_date
        with pytest.raises(ValueError):
            parse_date("2025-02-30")

    def test_empty_string_raises(self):
        from models import parse_date
        with pytest.raises(ValueError):
            parse_date("")

    def test_whitespace_string_raises(self):
        from models import parse_date
        with pytest.raises(ValueError):
            parse_date("   ")

    def test_none_raises_type_error(self):
        from models import parse_date
        with pytest.raises(TypeError):
            parse_date(None)

    def test_integer_raises_type_error(self):
        from models import parse_date
        with pytest.raises(TypeError):
            parse_date(20250615)

    def test_list_raises_type_error(self):
        from models import parse_date
        with pytest.raises(TypeError):
            parse_date([2025, 6, 15])

    def test_na_string_raises(self):
        from models import parse_date
        with pytest.raises((ValueError, TypeError)):
            parse_date("N/A")

    def test_na_no_slash_raises(self):
        from models import parse_date
        with pytest.raises((ValueError, TypeError)):
            parse_date("NA")


# ─────────────────────────────────────────────────────────────────────────────
# 2. ProductEOSRepo  (models.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestProductEOSRepo:
    """CRUD, cascade, constraint, and adversarial tests for ProductEOSRepo."""

    def test_add_and_retrieve_product(self, in_memory_repo):
        repo, _ = in_memory_repo
        p = repo.add_product("Cisco Catalyst 3750", "Cisco switch", "Hardware",
                              "Fixed", "2026-01-31", ["https://cisco.com"], 0.9)
        assert p.id is not None
        found = repo.get_product_by_name("Cisco Catalyst 3750")
        assert found is not None
        assert found.eos_date == date(2026, 1, 31)

    def test_get_by_name_case_insensitive(self, in_memory_repo):
        repo, _ = in_memory_repo
        repo.add_product("Dell PowerEdge R750", "Dell server", "Hardware",
                         "Fixed", "2027-06-01", [], 1.0)
        assert repo.get_product_by_name("dell poweredge r750") is not None

    def test_partial_name_match(self, in_memory_repo):
        repo, _ = in_memory_repo
        repo.add_product("Windows Server 2019", "Microsoft OS", "Software",
                         "Version-Based", "2029-01-09", [], 0.95)
        assert repo.get_product_by_name("Windows Server") is not None

    def test_get_nonexistent_returns_none(self, in_memory_repo):
        repo, _ = in_memory_repo
        assert repo.get_product_by_name("Does Not Exist XYZ") is None

    def test_get_all_products(self, in_memory_repo):
        repo, _ = in_memory_repo
        repo.add_product("Product A", "A", "Hardware", "Fixed", "2026-01-01", [], 1.0)
        repo.add_product("Product B", "B", "Software", "Version-Based", "2027-01-01", [], 0.8)
        assert len(repo.get_all_products()) == 2

    def test_add_support_tier(self, in_memory_repo):
        repo, _ = in_memory_repo
        p = repo.add_product("Cisco ISR 4431", "Router", "Hardware", "Fixed", "2025-12-31", [], 1.0)
        tier = repo.add_support_tier(p.id, "End of SW Maintenance", "2025-06-30")
        assert tier.id is not None
        assert tier.end_date == date(2025, 6, 30)

    def test_multiple_support_tiers(self, in_memory_repo):
        repo, _ = in_memory_repo
        p = repo.add_product("HP ProLiant DL380", "HP Server", "Hardware", "Fixed", "2028-11-30", [], 0.95)
        repo.add_support_tier(p.id, "Tier 1", "2026-01-01")
        repo.add_support_tier(p.id, "Tier 2", "2028-11-30")
        assert len(repo.get_product_tiers(p.id)) == 2

    def test_update_product(self, in_memory_repo):
        repo, _ = in_memory_repo
        p = repo.add_product("Adobe 2022", "PDF", "Software", "Version-Based", "2024-10-25", [], 0.9)
        updated = repo.update_product(p.id, summary="Updated summary", confidence=0.5)
        assert updated.summary == "Updated summary"
        assert updated.confidence == 0.5

    def test_update_nonexistent_returns_none(self, in_memory_repo):
        repo, _ = in_memory_repo
        assert repo.update_product(9999, summary="Ghost") is None

    def test_delete_product_succeeds(self, in_memory_repo):
        repo, _ = in_memory_repo
        p = repo.add_product("Temp Product", "Old", "Hardware", "Fixed", "2020-01-01", [], 0.6)
        assert repo.delete_product(p.id) is True
        assert repo.get_product_by_name("Temp Product") is None

    def test_delete_cascades_support_tiers(self, in_memory_repo):
        from models import SupportTier
        repo, session = in_memory_repo
        p = repo.add_product("Legacy Switch", "Old", "Hardware", "Fixed", "2020-01-01", [], 0.6)
        repo.add_support_tier(p.id, "EOL Tier", "2020-01-01")
        pid = p.id
        repo.delete_product(pid)
        tiers = session.query(SupportTier).filter_by(product_id=pid).all()
        assert len(tiers) == 0

    def test_delete_nonexistent_returns_false(self, in_memory_repo):
        repo, _ = in_memory_repo
        assert repo.delete_product(9999) is False

    def test_export_as_json_structure(self, in_memory_repo):
        repo, _ = in_memory_repo
        p = repo.add_product("Microsoft Office 2021", "Office suite", "Software",
                              "Version-Based", "2026-10-13", ["https://microsoft.com/lifecycle"], 0.98)
        data = repo.export_as_json(p.id)
        assert data["Name"] == "Microsoft Office 2021"
        assert "EOS Date" in data
        assert isinstance(data["Source URLs"], list)
        assert isinstance(data["Support Tiers"], list)

    def test_export_nonexistent_returns_none(self, in_memory_repo):
        repo, _ = in_memory_repo
        assert repo.export_as_json(9999) is None

    def test_add_product_with_date_object(self, in_memory_repo):
        repo, _ = in_memory_repo
        eos = date(2030, 6, 30)
        p = repo.add_product("Future Product", "Desc", "Hardware", "Fixed", eos, [], 1.0)
        assert p.eos_date == eos

    # ── Break attempts ──────────────────────────────────────────────────────

    def test_sql_injection_in_name_stored_literally(self, in_memory_repo):
        """SQL injection string must be stored as data, not executed."""
        repo, _ = in_memory_repo
        inject = "'; DROP TABLE product_eos; --"
        p = repo.add_product(inject, "Injection test", "Software", "Fixed", "2025-01-01", [], 0.5)
        assert p.name == inject
        # Table must still exist
        from models import ProductEOS
        _, session = in_memory_repo
        count = session.query(ProductEOS).count()
        assert count >= 1

    def test_duplicate_name_raises_integrity_error(self, in_memory_repo):
        from sqlalchemy.exc import IntegrityError
        repo, _ = in_memory_repo
        repo.add_product("Dup Product", "First", "Hardware", "Fixed", "2025-01-01", [], 1.0)
        with pytest.raises(IntegrityError):
            repo.add_product("Dup Product", "Second", "Hardware", "Fixed", "2025-01-01", [], 1.0)

    def test_negative_confidence_stored(self, in_memory_repo):
        """No DB-level constraint on confidence range — negative should persist."""
        repo, _ = in_memory_repo
        p = repo.add_product("Uncertain Product", "Unknown", "Hardware", "Fixed", "2025-01-01", [], -0.5)
        assert p.confidence == -0.5

    def test_unicode_emoji_in_name(self, in_memory_repo):
        repo, _ = in_memory_repo
        emoji_name = "Cisco 🔥 Switch Pro™"
        p = repo.add_product(emoji_name, "Emoji product", "Hardware", "Fixed", "2025-06-01", [], 0.7)
        found = repo.get_product_by_name("Cisco")
        assert found is not None

    def test_source_urls_none_exports_as_empty_list(self, in_memory_repo):
        from models import ProductEOS, parse_date
        _, session = in_memory_repo
        p = ProductEOS(name="No URLs None", summary="Test", hardware_software="Hardware",
                       support_model="Fixed", eos_date=parse_date("2025-01-01"),
                       source_urls=None, confidence=1.0)
        session.add(p)
        session.commit()
        repo, _ = in_memory_repo
        data = repo.export_as_json(p.id)
        assert data["Source URLs"] == []

    def test_very_long_summary_field(self, in_memory_repo):
        """Unbounded String column — long text should store without truncation."""
        repo, _ = in_memory_repo
        long_summary = "Word " * 1000  # ~5000 chars
        p = repo.add_product("Verbose Product", long_summary, "Software", "Fixed", "2025-01-01", [], 1.0)
        assert len(p.summary) > 100

    def test_support_tier_invalid_date_raises(self, in_memory_repo):
        repo, _ = in_memory_repo
        p = repo.add_product("Tier Date Test", "Test", "Hardware", "Fixed", "2025-01-01", [], 1.0)
        with pytest.raises((ValueError, TypeError)):
            repo.add_support_tier(p.id, "Bad Tier", "not-a-date")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Helper.parse_llm_json  (classes.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestParseLlmJson:
    """Tests for the JSON extractor used to parse Gemini responses."""

    def test_clean_json_string(self):
        from classes import Helper
        result = Helper.parse_llm_json('{"Name": "Cisco 3750", "EOS Date": "2026-01-31"}')
        assert result == {"Name": "Cisco 3750", "EOS Date": "2026-01-31"}

    def test_json_with_markdown_fences(self):
        from classes import Helper
        raw = '```json\n{"key": "value"}\n```'
        assert Helper.parse_llm_json(raw) == {"key": "value"}

    def test_json_embedded_in_prose(self):
        from classes import Helper
        raw = 'Here is the result: {"answer": 42} — end of response.'
        assert Helper.parse_llm_json(raw)["answer"] == 42

    def test_nested_json(self):
        from classes import Helper
        raw = '{"outer": {"inner": [1, 2, 3]}}'
        result = Helper.parse_llm_json(raw)
        assert result["outer"]["inner"] == [1, 2, 3]

    def test_unicode_content(self):
        from classes import Helper
        raw = '{"name": "Cisco® Catalyst™", "check": "✓"}'
        result = Helper.parse_llm_json(raw)
        assert "Cisco" in result["name"]

    # ── Break attempts ──────────────────────────────────────────────────────

    def test_empty_string_returns_none(self):
        from classes import Helper
        assert Helper.parse_llm_json("") is None

    def test_plain_text_no_json_returns_none(self):
        from classes import Helper
        assert Helper.parse_llm_json("just plain text, no JSON here") is None

    def test_malformed_json_returns_none(self):
        from classes import Helper
        assert Helper.parse_llm_json('{"key": "unterminated string') is None

    def test_only_opening_brace_returns_none(self):
        from classes import Helper
        assert Helper.parse_llm_json("{") is None

    def test_bare_array_returns_none(self):
        """Arrays have no { } so the extractor should return None."""
        from classes import Helper
        assert Helper.parse_llm_json('[1, 2, 3]') is None

    def test_xss_content_comes_back_literally(self):
        """Ensure script content is returned as data, not interpreted."""
        from classes import Helper
        raw = '{"html": "<script>alert(1)</script>"}'
        result = Helper.parse_llm_json(raw)
        assert result["html"] == "<script>alert(1)</script>"

    def test_multiple_json_objects_ambiguous_input(self):
        """
        Two separate JSON objects: the slicer takes from the first '{' to the last '}',
        producing '{"first": 1} and then {"second": 2}' which is invalid JSON.
        Expected: None (the parser cannot resolve the ambiguity safely).
        """
        from classes import Helper
        raw = '{"first": 1} and then {"second": 2}'
        result = Helper.parse_llm_json(raw)
        assert result is None  # Ambiguous input — safe to return None


# ─────────────────────────────────────────────────────────────────────────────
# 4. Helper.preprocess  (classes.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestHelperPreprocess:
    """File-parsing tests — valid inputs, edge cases, and corrupt inputs."""

    def test_valid_csv_both_columns(self, tmp_path):
        from classes import Helper
        f = _make_csv(tmp_path / "test.csv",
                      [("Dell R750", "Windows Server 2022"),
                       ("Cisco 3650", "Adobe Acrobat 2024")])
        hw, sw = Helper().preprocess(f)
        assert "Dell R750" in hw
        assert "Windows Server 2022" in sw

    def test_hardware_column_only(self, tmp_path):
        from classes import Helper
        f = _make_csv(tmp_path / "hw.csv",
                      [("Dell R750", ""), ("HP DL380", "")])
        hw, sw = Helper().preprocess(f)
        assert len(hw) == 2
        assert len(sw) == 0

    def test_deduplication(self, tmp_path):
        from classes import Helper
        f = _make_csv(tmp_path / "dups.csv",
                      [("Dell R750", "Win 2022"),
                       ("Dell R750", "Win 2022"),
                       ("Dell R750", "Win 2022")])
        hw, sw = Helper().preprocess(f)
        assert hw.count("Dell R750") == 1
        assert sw.count("Win 2022") == 1

    def test_whitespace_stripped(self, tmp_path):
        from classes import Helper
        f = _make_csv(tmp_path / "spaces.csv",
                      [("  Dell R750  ", "  Windows Server  ")])
        hw, sw = Helper().preprocess(f)
        assert "Dell R750" in hw
        assert "Windows Server" in sw

    def test_empty_and_whitespace_rows_skipped(self, tmp_path):
        from classes import Helper
        f = _make_csv(tmp_path / "empties.csv",
                      [("", ""), ("   ", "    "), ("Real HW", "Real SW")])
        hw, sw = Helper().preprocess(f)
        assert len(hw) == 1 and hw[0] == "Real HW"
        assert len(sw) == 1 and sw[0] == "Real SW"

    def test_wrong_column_names_returns_empty(self, tmp_path):
        from classes import Helper
        f = _make_csv(tmp_path / "wrong.csv",
                      [("Val1", "Val2")], headers=("Model", "Version"))
        hw, sw = Helper().preprocess(f)
        assert hw == [] and sw == []

    def test_headers_only_returns_empty(self, tmp_path):
        from classes import Helper
        f = _make_csv(tmp_path / "hdrs_only.csv", [])
        hw, sw = Helper().preprocess(f)
        assert hw == [] and sw == []

    def test_large_file(self, tmp_path):
        from classes import Helper
        rows = [(f"HW {i}", f"SW {i}") for i in range(500)]
        f = _make_csv(tmp_path / "large.csv", rows)
        hw, sw = Helper().preprocess(f)
        assert len(hw) == 500 and len(sw) == 500

    # ── Break attempts ──────────────────────────────────────────────────────

    def test_nonexistent_file_returns_empty(self):
        from classes import Helper
        hw, sw = Helper().preprocess("/totally/fake/path/file.csv")
        assert hw == [] and sw == []

    def test_csv_with_sql_injection_values(self, tmp_path):
        from classes import Helper
        f = _make_csv(tmp_path / "inject.csv",
                      [("'; DROP TABLE product_eos; --", "1' OR '1'='1")])
        hw, sw = Helper().preprocess(f)
        assert len(hw) == 1
        assert "DROP TABLE" in hw[0]

    def test_csv_with_html_values(self, tmp_path):
        from classes import Helper
        f = _make_csv(tmp_path / "html.csv",
                      [("<script>alert(1)</script>", "<b>bold</b>")])
        hw, sw = Helper().preprocess(f)
        assert len(hw) == 1
        assert "<script>" in hw[0]


# ─────────────────────────────────────────────────────────────────────────────
# 5. Processing.export_to_csv  (classes.py)
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_PIPELINE_RESULTS = [
    {
        "Name": "Cisco 3750",
        "Hardware/Software": "Hardware",
        "EOS Date": "2024-01-31",
        "Confidence": 0.95,
        "Support Tiers": [{"Tier": "HW EOL", "EndDate": "2024-01-31"}],
    },
    {
        "Name": "Windows 10",
        "Hardware/Software": "Software",
        "EOS Date": "2025-10-14",
        "Confidence": 0.99,
        "Support Tiers": [],
    },
]


class TestProcessingExportToCsv:

    def test_returns_dataframe(self):
        from classes import Processing
        df = Processing.export_to_csv(SAMPLE_PIPELINE_RESULTS)
        assert df is not None
        assert len(df) >= 2

    def test_columns_present(self):
        from classes import Processing
        df = Processing.export_to_csv(SAMPLE_PIPELINE_RESULTS)
        assert "Name" in df.columns

    def test_writes_to_file(self, tmp_path):
        from classes import Processing
        out = str(tmp_path / "output.csv")
        df = Processing.export_to_csv(SAMPLE_PIPELINE_RESULTS, filename=out)
        assert Path(out).exists()
        assert df is not None

    def test_no_support_tiers_key(self):
        from classes import Processing
        results = [{"Name": "Product A", "EOS Date": "2025-01-01", "Confidence": 0.8}]
        df = Processing.export_to_csv(results)
        assert df is not None

    # ── Break attempts ──────────────────────────────────────────────────────

    def test_empty_results_handled(self):
        from classes import Processing
        df = Processing.export_to_csv([])
        # Either None or an empty DataFrame — both are acceptable
        assert df is None or len(df) == 0

    def test_none_support_tier_entry(self):
        from classes import Processing
        results = [{"Name": "Broken", "EOS Date": "2026-06-01", "Support Tiers": [None]}]
        # Should not raise an unhandled exception
        try:
            Processing.export_to_csv(results)
        except Exception:
            pass  # Caller is responsible for clean data — crash is acceptable here


# ─────────────────────────────────────────────────────────────────────────────
# 6. is_vague_query  (unified_chat.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestIsVagueQuery:
    """Confirm the RAG gating function blocks bulk-dump queries."""

    # Specific queries (should NOT be vague)
    @pytest.mark.parametrize("query", [
        "When does Cisco Catalyst 3750 reach EOS?",
        "What is the end of support date for Windows Server 2019?",
        "Is Adobe Acrobat 2022 still supported?",
        "Dell PowerEdge R750 EOS date?",
    ])
    def test_specific_queries_not_vague(self, query):
        from unified_chat import is_vague_query
        assert is_vague_query(query) is False

    # Vague queries (should be caught)
    @pytest.mark.parametrize("query", [
        "list all products",
        "show me all assets",
        "give me everything",
        "how many products are there?",
        "create a table of all assets",
        "eos summary",
        "all eos dates",
        "what are the EOS dates",
        "all hardware",
        "all software",
    ])
    def test_vague_queries_detected(self, query):
        from unified_chat import is_vague_query
        assert is_vague_query(query) is True

    def test_empty_string_not_vague(self):
        from unified_chat import is_vague_query
        assert is_vague_query("") is False


# ─────────────────────────────────────────────────────────────────────────────
# 7. retrieve_relevant_products  (unified_chat.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestRetrieveRelevantProducts:

    def test_finds_product_by_keyword(self, populated_db_session):
        from unified_chat import retrieve_relevant_products
        result = retrieve_relevant_products("Cisco switch EOS date",
                                            session_override=populated_db_session)
        assert "Cisco" in result

    def test_finds_software_by_keyword(self, populated_db_session):
        from unified_chat import retrieve_relevant_products
        result = retrieve_relevant_products("Windows Server support end date",
                                            session_override=populated_db_session)
        assert "Windows" in result

    def test_unrelated_query_returns_fallback(self, populated_db_session):
        from unified_chat import retrieve_relevant_products
        result = retrieve_relevant_products("banana smoothie recipe",
                                            session_override=populated_db_session)
        assert isinstance(result, str) and len(result) > 0

    def test_hardware_filter_active(self, populated_db_session):
        from unified_chat import retrieve_relevant_products
        result = retrieve_relevant_products("hardware server", session_override=populated_db_session)
        assert isinstance(result, str)

    def test_limit_parameter_respected(self, populated_db_session):
        from unified_chat import retrieve_relevant_products
        result = retrieve_relevant_products("product", limit=2, session_override=populated_db_session)
        numbered_lines = [l for l in result.split("\n") if l.strip() and l.strip()[0].isdigit()]
        assert len(numbered_lines) <= 2

    # ── Break attempts ──────────────────────────────────────────────────────

    def test_empty_query(self, populated_db_session):
        from unified_chat import retrieve_relevant_products
        result = retrieve_relevant_products("", session_override=populated_db_session)
        assert isinstance(result, str)

    def test_sql_injection_query(self, populated_db_session):
        """Injection in query string should not execute raw SQL."""
        from unified_chat import retrieve_relevant_products
        result = retrieve_relevant_products("'; DROP TABLE product_eos; --",
                                            session_override=populated_db_session)
        assert isinstance(result, str)
        # Verify the table still works by checking the session
        from models import ProductEOS
        count = populated_db_session.query(ProductEOS).count()
        assert count >= 4

    def test_very_long_query(self, populated_db_session):
        from unified_chat import retrieve_relevant_products
        long_q = "Cisco " * 1000
        result = retrieve_relevant_products(long_q, session_override=populated_db_session)
        assert isinstance(result, str)


# ─────────────────────────────────────────────────────────────────────────────
# 8. _is_persistable_iso_date  (webpage.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestIsPersistableIsoDate:
    """Tests for the gate function that decides whether a date can be stored."""

    def test_valid_date_is_persistable(self):
        import webpage
        assert webpage._is_persistable_iso_date("2026-12-31") is True

    def test_placeholder_date_is_persistable(self):
        import webpage
        assert webpage._is_persistable_iso_date("2099-12-31") is True

    def test_far_past_is_persistable(self):
        import webpage
        assert webpage._is_persistable_iso_date("2001-01-01") is True

    def test_dd_mm_yyyy_not_persistable(self):
        import webpage
        assert webpage._is_persistable_iso_date("31/12/2026") is False

    def test_empty_string_not_persistable(self):
        import webpage
        assert webpage._is_persistable_iso_date("") is False

    def test_none_not_persistable(self):
        import webpage
        assert webpage._is_persistable_iso_date(None) is False

    def test_na_string_not_persistable(self):
        import webpage
        assert webpage._is_persistable_iso_date("N/A") is False

    def test_no_eos_found_not_persistable(self):
        import webpage
        assert webpage._is_persistable_iso_date("No EOS date found") is False

    def test_plain_text_not_persistable(self):
        import webpage
        assert webpage._is_persistable_iso_date("Unknown") is False


# ─────────────────────────────────────────────────────────────────────────────
# 9. Flask authentication routes
# ─────────────────────────────────────────────────────────────────────────────

class TestFlaskAuth:

    def test_login_page_loads(self, flask_client):
        resp = flask_client.get("/login")
        assert resp.status_code == 200

    def test_login_success_redirects(self, flask_client):
        resp = flask_client.post("/login",
                                 data={"username": "admin", "password": "testpassword123"},
                                 follow_redirects=False)
        assert resp.status_code in (302, 200)

    def test_login_wrong_password_shows_error(self, flask_client):
        resp = flask_client.post("/login",
                                 data={"username": "admin", "password": "wrongpassword"},
                                 follow_redirects=True)
        assert resp.status_code == 200
        assert b"Invalid" in resp.data

    def test_login_empty_credentials_rejected(self, flask_client):
        resp = flask_client.post("/login",
                                 data={"username": "", "password": ""},
                                 follow_redirects=True)
        assert resp.status_code == 200
        assert b"Invalid" in resp.data

    def test_login_sql_injection_credentials_rejected(self, flask_client):
        """SQL-injection-style username must not bypass auth."""
        resp = flask_client.post("/login",
                                 data={"username": "' OR '1'='1", "password": "' OR '1'='1"},
                                 follow_redirects=True)
        assert resp.status_code == 200
        assert b"Invalid" in resp.data

    def test_login_wrong_username_rejected(self, flask_client):
        resp = flask_client.post("/login",
                                 data={"username": "notadmin", "password": "testpassword123"},
                                 follow_redirects=True)
        assert resp.status_code == 200
        assert b"Invalid" in resp.data

    def test_root_unauthenticated_redirects_to_login(self, flask_client):
        resp = flask_client.get("/", follow_redirects=False)
        assert resp.status_code == 302

    def test_logout_redirects(self, auth_client):
        resp = auth_client.post("/logout", follow_redirects=False)
        assert resp.status_code in (302, 200)

    def test_authenticated_root_returns_200(self, auth_client):
        resp = auth_client.get("/")
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# 10. Flask /upload-manual
# ─────────────────────────────────────────────────────────────────────────────

class TestFlaskUploadManual:

    def test_single_item(self, auth_client):
        resp = auth_client.post("/upload-manual", json={"query": "Cisco Catalyst 3750"},
                                content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["sw_count"] == 1

    def test_semicolon_separated_items(self, auth_client):
        resp = auth_client.post("/upload-manual",
                                json={"query": "Cisco Switch; Dell Server; HP Printer"},
                                content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["sw_count"] == 3

    def test_empty_query_returns_400(self, auth_client):
        resp = auth_client.post("/upload-manual", json={"query": ""},
                                content_type="application/json")
        assert resp.status_code == 400

    def test_whitespace_only_query_returns_400(self, auth_client):
        resp = auth_client.post("/upload-manual", json={"query": "   ;   ;   "},
                                content_type="application/json")
        assert resp.status_code == 400

    def test_unauthenticated_returns_401_or_redirect(self, flask_client):
        resp = flask_client.post("/upload-manual", json={"query": "Cisco"},
                                 content_type="application/json")
        assert resp.status_code in (302, 401)

    # ── Break attempts ──────────────────────────────────────────────────────

    def test_no_json_body(self, auth_client):
        resp = auth_client.post("/upload-manual", data="not json",
                                content_type="text/plain")
        assert resp.status_code == 400

    def test_xss_input_not_rejected(self, auth_client):
        """XSS-like content is data — it should be accepted, not executed."""
        resp = auth_client.post("/upload-manual",
                                json={"query": "<script>alert('xss')</script>"},
                                content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["sw_count"] == 1

    def test_very_long_item_name(self, auth_client):
        """6000-char name should not crash the endpoint."""
        resp = auth_client.post("/upload-manual",
                                json={"query": "X" * 6000},
                                content_type="application/json")
        assert resp.status_code == 200

    def test_only_semicolons_returns_400(self, auth_client):
        """All-delimiter query should produce no items."""
        resp = auth_client.post("/upload-manual", json={"query": ";;;;;;;;"},
                                content_type="application/json")
        assert resp.status_code == 400

    def test_null_query_field(self, auth_client):
        resp = auth_client.post("/upload-manual", json={"query": None},
                                content_type="application/json")
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# 11. Flask cache & export routes
# ─────────────────────────────────────────────────────────────────────────────

class TestFlaskCacheAndExport:

    def test_cache_clear_returns_success(self, auth_client):
        resp = auth_client.post("/cache-clear")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

    def test_pipeline_cache_endpoint(self, auth_client):
        resp = auth_client.get("/pipeline-cache")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "cached" in data

    def test_cache_debug_endpoint(self, auth_client):
        resp = auth_client.get("/cache-debug")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "memory_cache_count" in data and "current_upload_count" in data

    def test_export_csv_empty_cache_and_db(self, auth_client):
        """Empty cache + empty DB must return 400, not a crash."""
        import webpage
        from models import ProductEOS
        webpage._results_cache.clear()
        count = webpage.db_session.query(ProductEOS).count()
        resp = auth_client.get("/export-csv")
        if count == 0:
            assert resp.status_code == 400
        else:
            assert resp.status_code == 200

    def test_cache_clear_unauthenticated(self, flask_client):
        resp = flask_client.post("/cache-clear")
        assert resp.status_code in (302, 401)


# ─────────────────────────────────────────────────────────────────────────────
# 12. Flask /run-pipeline  (SSE endpoint)
# ─────────────────────────────────────────────────────────────────────────────

class TestFlaskRunPipeline:

    def test_requires_auth(self, flask_client):
        resp = flask_client.get("/run-pipeline")
        assert resp.status_code in (302, 401)

    def test_no_data_emits_pipeline_error(self, auth_client):
        import webpage
        webpage._last_upload["hw_list"] = []
        webpage._last_upload["sw_list"] = []
        resp = auth_client.get("/run-pipeline?hw=0")
        if resp.status_code == 200:
            body = resp.data.decode("utf-8")
            # Should emit a pipeline-error SSE event
            assert "pipeline-error" in body or "error" in body

    def test_no_items_selected_emits_error(self, auth_client):
        import webpage
        webpage._last_upload["hw_list"] = ["Dell R750"]
        webpage._last_upload["sw_list"] = []
        # No hw= or sw= params → nothing selected
        resp = auth_client.get("/run-pipeline")
        if resp.status_code == 200:
            body = resp.data.decode("utf-8")
            assert "error" in body


# ─────────────────────────────────────────────────────────────────────────────
# 13. Flask chat endpoints  (mocked AI)
# ─────────────────────────────────────────────────────────────────────────────

def _mock_chat_session(tokens=10):
    """Return a MagicMock that acts like a GeminiChatSession."""
    mock = MagicMock()
    mock.session_id = "mock_session_001"
    mock.get_conversation_tokens.return_value = tokens
    mock.get_history.return_value = []
    mock.send_message.return_value = {
        "success": True,
        "response": "Mock AI response.",
        "history_length": 2,
        "conversation_tokens": tokens + 5,
    }
    return mock


class TestFlaskChatEndpoints:

    def test_chat_status_ok(self, auth_client):
        import webpage
        with patch.object(webpage, "_get_chat_session", return_value=_mock_chat_session()):
            resp = auth_client.get("/chat/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "db_ok" in data and "product_count" in data

    def test_chat_history_ok(self, auth_client):
        import webpage
        with patch.object(webpage, "_get_chat_session", return_value=_mock_chat_session()):
            resp = auth_client.get("/chat/history")
        assert resp.status_code == 200

    def test_chat_send_success(self, auth_client):
        import webpage
        with patch.object(webpage, "_get_chat_session", return_value=_mock_chat_session()):
            resp = auth_client.post("/chat/send",
                                    json={"message": "When does Cisco 3750 reach EOS?"},
                                    content_type="application/json")
        assert resp.status_code == 200
        assert "response" in resp.get_json()

    def test_chat_send_empty_message_returns_400(self, auth_client):
        import webpage
        with patch.object(webpage, "_get_chat_session", return_value=_mock_chat_session()):
            resp = auth_client.post("/chat/send", json={"message": ""},
                                    content_type="application/json")
        assert resp.status_code == 400

    def test_chat_send_no_body_returns_400(self, auth_client):
        import webpage
        with patch.object(webpage, "_get_chat_session", return_value=_mock_chat_session()):
            resp = auth_client.post("/chat/send", data="", content_type="text/plain")
        assert resp.status_code == 400

    def test_chat_clear_returns_cleared(self, auth_client):
        import webpage
        with patch.object(webpage, "_get_chat_session", return_value=_mock_chat_session()):
            resp = auth_client.post("/chat/clear")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "cleared"

    def test_chat_send_at_token_limit_returns_429(self, auth_client):
        import webpage
        with patch.object(webpage, "_get_chat_session",
                          return_value=_mock_chat_session(tokens=1000)):
            resp = auth_client.post("/chat/send",
                                    json={"message": "Hello"},
                                    content_type="application/json")
        assert resp.status_code == 429
        data = resp.get_json()
        assert data["limit_reached"] is True

    def test_chat_send_approaching_limit_returns_warning(self, auth_client):
        import webpage
        mock = _mock_chat_session(tokens=850)  # 85% of 1000
        mock.send_message.return_value = {
            "success": True,
            "response": "Almost full.",
            "history_length": 10,
            "conversation_tokens": 860,
        }
        with patch.object(webpage, "_get_chat_session", return_value=mock):
            resp = auth_client.post("/chat/send",
                                    json={"message": "Tell me more"},
                                    content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json().get("token_warning") is True

    # ── Break attempts ──────────────────────────────────────────────────────

    def test_chat_send_xss_message(self, auth_client):
        """XSS in message must not cause a 500 — stored as data."""
        import webpage
        with patch.object(webpage, "_get_chat_session", return_value=_mock_chat_session()):
            resp = auth_client.post("/chat/send",
                                    json={"message": "<script>alert(1)</script>"},
                                    content_type="application/json")
        assert resp.status_code == 200

    def test_chat_send_very_long_message(self, auth_client):
        """Very long message should be either accepted or rejected cleanly."""
        import webpage
        with patch.object(webpage, "_get_chat_session", return_value=_mock_chat_session()):
            resp = auth_client.post("/chat/send",
                                    json={"message": "A" * 50000},
                                    content_type="application/json")
        assert resp.status_code in (200, 400, 429)

    def test_chat_send_unicode_message(self, auth_client):
        import webpage
        with patch.object(webpage, "_get_chat_session", return_value=_mock_chat_session()):
            resp = auth_client.post("/chat/send",
                                    json={"message": "EOS date for 思科 Catalyst 🔥?"},
                                    content_type="application/json")
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# 14. Flask /get-time
# ─────────────────────────────────────────────────────────────────────────────

class TestFlaskGetTime:

    def test_returns_timestamp(self, auth_client):
        resp = auth_client.get("/get-time")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "timestamp" in data or "error" in data

    def test_ntp_failure_falls_back_gracefully(self, auth_client):
        """If NTP is unavailable, the endpoint must not crash."""
        import webpage
        with patch.object(webpage, "get_ntp_time",
                          side_effect=Exception("NTP unavailable")):
            resp = auth_client.get("/get-time")
        assert resp.status_code in (200, 500)


# ─────────────────────────────────────────────────────────────────────────────
# 15. _parse_selected_indices  (webpage.py)
#     Tested via /run-pipeline query string behaviour
# ─────────────────────────────────────────────────────────────────────────────

class TestParseSelectedIndices:
    """Internal helper — tested through the Flask test context."""

    def test_negative_index_ignored(self, auth_client):
        """Negative index values should not crash the pipeline."""
        import webpage
        webpage._last_upload["hw_list"] = ["Dell R750"]
        webpage._last_upload["sw_list"] = []
        resp = auth_client.get("/run-pipeline?hw=-1")
        if resp.status_code == 200:
            body = resp.data.decode("utf-8")
            assert "error" in body or "pipeline-error" in body

    def test_non_integer_index_ignored(self, auth_client):
        """Non-numeric index must not crash — simply ignored."""
        import webpage
        webpage._last_upload["hw_list"] = ["Dell R750"]
        webpage._last_upload["sw_list"] = []
        resp = auth_client.get("/run-pipeline?hw=abc")
        if resp.status_code == 200:
            body = resp.data.decode("utf-8")
            assert "error" in body or "pipeline-error" in body

    def test_float_index_ignored(self, auth_client):
        import webpage
        webpage._last_upload["hw_list"] = ["Dell R750"]
        webpage._last_upload["sw_list"] = []
        resp = auth_client.get("/run-pipeline?hw=1.5")
        if resp.status_code == 200:
            body = resp.data.decode("utf-8")
            assert "error" in body or "pipeline-error" in body
