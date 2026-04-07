import asyncio
from unittest.mock import patch

import pytest

import webpage
from models import Base, ProductEOS, ProductEOSRepo, init_database, parse_date


@pytest.fixture()
def client_and_session():
    engine, session = init_database("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    repo = ProductEOSRepo(session)

    # Seed 4 assets for update/export test coverage.
    p1 = repo.add_product(
        name="Cisco IOS 7.8",
        summary="Old summary 1",
        hardware_software="Software",
        support_model="Version-Based",
        eos_date="2005-07-28",
        source_urls=["https://example.com/old1"],
        confidence=0.70,
    )
    repo.add_support_tier(product_id=p1.id, tier_name="Old Tier", end_date="2004-01-01")

    p2 = repo.add_product(
        name="Ubuntu 22.04 LTS",
        summary="Old summary 2",
        hardware_software="Software",
        support_model="Fixed",
        eos_date="2032-04-01",
        source_urls=["https://example.com/old2"],
        confidence=0.90,
    )
    p3 = repo.add_product(
        name="iPhone 16 Pro",
        summary="Old summary 3",
        hardware_software="Hardware",
        support_model="Version-Based",
        eos_date="2030-09-01",
        source_urls=["https://example.com/old3"],
        confidence=0.85,
    )
    p4 = repo.add_product(
        name="Adobe Photoshop 2024",
        summary="Old summary 4",
        hardware_software="Software",
        support_model="Version-Based",
        eos_date="2029-12-31",
        source_urls=["https://example.com/old4"],
        confidence=0.80,
    )

    webpage.db_engine = engine
    webpage.db_session = session
    webpage.product_repo = repo

    app = webpage.app
    app.config["TESTING"] = True

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user"] = "admin"
        yield client, session, {"p1": p1.id, "p2": p2.id, "p3": p3.id, "p4": p4.id}

    Base.metadata.drop_all(engine)
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def mock_external_ai_calls():
    async def _fake_process_line(name, client, config, instruct):
        return {
            "Name": name,
            "Summary": "Mocked API result",
            "Hardware/Software": "Software",
            "Support Model": "Version-Based",
            "EOS Date": "2031-01-01",
            "Support Tiers": [{"Tier": "General Support", "EndDate": "2031-01-01"}],
            "Source URLs": ["https://example.com/mock"],
            "Confidence": 0.88,
        }

    with (
        patch.object(webpage, "keys_and_prompt_setup", return_value=("mock_keys", "mock_instructions")),
        patch.object(webpage, "client_setup", return_value=("mock_client", "mock_config")),
        patch.object(webpage, "process_line", side_effect=_fake_process_line),
    ):
        yield


def test_patch_single_asset_updates_existing_record(client_and_session):
    client, session, ids = client_and_session
    product_id = ids["p1"]

    new_payload = {
        "Name": "Cisco IOS 7.8",
        "Summary": "Updated summary from retrigger",
        "Hardware/Software": "Software",
        "Support Model": "Version-Based",
        "EOS Date": "2006-08-15",
        "Support Tiers": [
            {"Tier": "End of Support", "EndDate": "2006-08-15"},
        ],
        "Source URLs": ["https://example.com/new-cisco"],
        "Confidence": 0.97,
    }

    resp = client.patch("/refresh-item", json={"id": product_id, "result": new_payload})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True

    session.expire_all()
    product = session.query(ProductEOS).filter(ProductEOS.id == product_id).first()
    assert product is not None
    assert product.summary == "Updated summary from retrigger"
    assert product.eos_date == parse_date("2006-08-15")
    assert product.source_urls == ["https://example.com/new-cisco"]
    assert abs(product.confidence - 0.97) < 1e-9
    assert len(product.support_tiers) == 1
    assert product.support_tiers[0].tier == "End of Support"


def test_post_refresh_item_returns_preview_without_db_overwrite(client_and_session):
    client, session, ids = client_and_session
    product_id = ids["p1"]

    before = session.query(ProductEOS).filter(ProductEOS.id == product_id).first()
    assert before is not None
    before_summary = before.summary

    resp = client.post(
        "/refresh-item",
        json={"item_name": "Cisco IOS 7.8", "item_type": "sw"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["asset_id"] == product_id
    assert isinstance(data.get("old_result"), dict)
    assert isinstance(data.get("result"), dict)
    assert data["result"]["Summary"] == "Mocked API result"

    # POST is preview-only. Database should remain unchanged until PATCH confirm.
    session.expire_all()
    after = session.query(ProductEOS).filter(ProductEOS.id == product_id).first()
    assert after is not None
    assert after.summary == before_summary


def test_patch_invalid_missing_data_returns_400_and_keeps_db_unchanged(client_and_session):
    client, session, ids = client_and_session
    product_id = ids["p2"]

    before = session.query(ProductEOS).filter(ProductEOS.id == product_id).first()
    assert before is not None
    before_summary = before.summary
    before_eos = before.eos_date

    invalid_payload = {
        "Name": "Ubuntu 22.04 LTS",
        "Summary": "Should not be saved",
        "Hardware/Software": "Software",
        "EOS Date": "",  # Missing/invalid for required field
        "Support Model": "Fixed",
        "Support Tiers": [],
        "Source URLs": [],
        "Confidence": 0.1,
    }

    resp = client.patch("/refresh-item", json={"id": product_id, "result": invalid_payload})
    assert resp.status_code == 400

    session.expire_all()
    after = session.query(ProductEOS).filter(ProductEOS.id == product_id).first()
    assert after is not None
    assert after.summary == before_summary
    assert after.eos_date == before_eos


def test_patch_non_hw_sw_classification_returns_400_and_keeps_db_unchanged(client_and_session):
    client, session, ids = client_and_session
    product_id = ids["p3"]

    before = session.query(ProductEOS).filter(ProductEOS.id == product_id).first()
    assert before is not None
    before_summary = before.summary
    before_type = before.hardware_software

    payload = {
        "Name": "iPhone 16 Pro",
        "Summary": "Should not persist",
        "Hardware/Software": "N/A",
        "EOS Date": "2031-01-01",
        "Support Model": "Version-Based",
        "Support Tiers": [],
        "Source URLs": [],
        "Confidence": 0.5,
    }

    resp = client.patch("/refresh-item", json={"id": product_id, "result": payload})
    assert resp.status_code == 400

    session.expire_all()
    after = session.query(ProductEOS).filter(ProductEOS.id == product_id).first()
    assert after is not None
    assert after.summary == before_summary
    assert after.hardware_software == before_type


def test_export_with_valid_selected_ids_returns_only_those_rows(client_and_session):
    client, _session, ids = client_and_session

    selected_ids = [ids["p1"], ids["p3"]]
    resp = client.post("/export-csv", json={"ids": selected_ids})

    assert resp.status_code == 200
    assert "text/csv" in resp.content_type

    csv_text = resp.data.decode("utf-8")
    assert "Cisco IOS 7.8" in csv_text
    assert "iPhone 16 Pro" in csv_text
    assert "Ubuntu 22.04 LTS" not in csv_text
    assert "Adobe Photoshop 2024" not in csv_text


def test_export_with_empty_id_list_returns_error(client_and_session):
    client, _session, _ids = client_and_session

    resp = client.post("/export-csv", json={"ids": []})
    assert resp.status_code == 400
    data = resp.get_json()
    assert "error" in data


def test_export_with_non_existent_ids_is_graceful(client_and_session):
    client, _session, _ids = client_and_session

    resp = client.post("/export-csv", json={"ids": [999999, 999998]})
    assert resp.status_code != 500
    data = resp.get_json()
    assert isinstance(data, dict)
    assert "error" in data


def test_export_humanizes_placeholder_eos_date(client_and_session):
    client, session, ids = client_and_session

    product = session.query(ProductEOS).filter(ProductEOS.id == ids["p4"]).first()
    assert product is not None
    product.eos_date = parse_date("2099-12-31")
    session.commit()

    resp = client.post("/export-csv", json={"ids": [ids["p4"]]})
    assert resp.status_code == 200
    csv_text = resp.data.decode("utf-8")
    assert "No EOS found" in csv_text
    assert "2099-12-31" not in csv_text
