"""Port reference data: loading, reading, and the not-configured boundary.

The load path is tested for what it refuses as much as for what it accepts. A
gazetteer that silently drops malformed rows leaves the operator believing they
have a complete registry, which is the failure this module exists to prevent.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pymongo.database import Database

from app.config import get_settings
from app.db import collections, indexes
from app.domain.ais import parse_row
from app.ingest.pipeline import build_latest_update, build_position_document
from app.services import ports
from tests.conftest import ais_row

pytestmark = pytest.mark.integration

BASE = datetime(2025, 1, 8, 12, 0, 0, tzinfo=UTC)

PORT_CSV = """id,name,latitude,longitude,country,unlocode,harbourSize,ignored
USNYC,Port of New York,40.05,-74.02,United States,USNYC,Large,whatever
USLAX,Port of Los Angeles,33.72,-118.27,United States,USLAX,Large,whatever
"""


@pytest.fixture
def client(
    test_database: Database[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    from app.db import client as db_client

    settings = get_settings()
    monkeypatch.setattr(settings, "mongodb_database", settings.mongodb_test_database)
    db_client._async_client = None

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
    db_client._async_client = None


@pytest.fixture
def port_file(tmp_path: Path) -> Path:
    path = tmp_path / "ports.csv"
    path.write_text(PORT_CSV, encoding="utf-8")
    return path


# ---------------------------------------------------------------- not configured
def test_ports_report_not_configured_rather_than_an_empty_list(client: TestClient) -> None:
    """An empty array would say "no ports exist", which is a different claim."""
    response = client.get("/api/v1/ports")
    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "PORT_DATA_NOT_CONFIGURED"
    assert "navisight-data ports load" in body["message"]


def test_dataset_status_reports_ports_unconfigured(client: TestClient) -> None:
    assert client.get("/api/v1/dataset/status").json()["portsConfigured"] is False


# ------------------------------------------------------------------------ loading
def test_load_reads_a_csv_and_ignores_extra_columns(
    test_database: Database[dict[str, Any]], port_file: Path
) -> None:
    summary = ports.load(test_database, port_file)
    assert summary["total"] == 2

    stored = test_database[collections.PORTS].find_one({"_id": "USNYC"})
    assert stored is not None
    assert stored["name"] == "Port of New York"
    # GeoJSON order is [longitude, latitude]. Always.
    assert stored["location"]["coordinates"] == [-74.02, 40.05]
    assert stored["source"] == "ports.csv"
    assert "ignored" not in stored


def test_load_is_idempotent(test_database: Database[dict[str, Any]], port_file: Path) -> None:
    ports.load(test_database, port_file)
    ports.load(test_database, port_file)
    assert test_database[collections.PORTS].estimated_document_count() == 2


def test_load_reads_geojson(test_database: Database[dict[str, Any]], tmp_path: Path) -> None:
    path = tmp_path / "ports.geojson"
    path.write_text(
        """{"type":"FeatureCollection","features":[
          {"type":"Feature","id":"GBLON",
           "geometry":{"type":"Point","coordinates":[0.05,51.5]},
           "properties":{"name":"Port of London","country":"United Kingdom"}}]}""",
        encoding="utf-8",
    )
    ports.load(test_database, path)
    stored = test_database[collections.PORTS].find_one({"_id": "GBLON"})
    assert stored is not None
    assert stored["location"]["coordinates"] == [0.05, 51.5]


@pytest.mark.parametrize(
    ("csv_text", "expected"),
    [
        ("name,latitude,longitude\nA,1,2\n", "missing required column"),
        ("id,name,latitude,longitude\n,A,1,2\n", "id is empty"),
        ("id,name,latitude,longitude\nX,,1,2\n", "name is empty"),
        ("id,name,latitude,longitude\nX,A,1,999\n", "outside"),
        ("id,name,latitude,longitude\nX,A,north,2\n", "is not a number"),
    ],
)
def test_a_malformed_row_aborts_rather_than_being_skipped(
    test_database: Database[dict[str, Any]], tmp_path: Path, csv_text: str, expected: str
) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(csv_text, encoding="utf-8")
    with pytest.raises(ports.PortLoadError, match=expected):
        ports.load(test_database, path)


def test_a_missing_file_is_reported_clearly(
    test_database: Database[dict[str, Any]], tmp_path: Path
) -> None:
    with pytest.raises(ports.PortLoadError, match="does not exist"):
        ports.load(test_database, tmp_path / "absent.csv")


# ------------------------------------------------------------------------ reading
@pytest.fixture
def loaded(test_database: Database[dict[str, Any]], port_file: Path) -> Database[dict[str, Any]]:
    indexes.ensure_indexes(test_database)
    ports.load(test_database, port_file)

    # One vessel a few hundred metres from New York, one on the far coast.
    records = [
        parse_row(
            ais_row(mmsi="366000001", at=BASE, longitude=-74.021, latitude=40.051, name="NEARBY")
        ),
        parse_row(
            ais_row(mmsi="366000002", at=BASE, longitude=-118.27, latitude=33.72, name="FAR WEST")
        ),
    ]
    test_database[collections.VESSEL_POSITIONS].insert_many(
        [build_position_document(r, dataset="TEST", source_file="t.csv") for r in records]
    )
    test_database[collections.VESSEL_LATEST].bulk_write([build_latest_update(r) for r in records])
    return test_database


def test_list_and_search(client: TestClient, loaded: Database[dict[str, Any]]) -> None:
    assert len(client.get("/api/v1/ports").json()) == 2

    matches = client.get("/api/v1/ports", params={"q": "angeles"}).json()
    assert [port["id"] for port in matches] == ["USLAX"]

    assert client.get("/api/v1/ports", params={"q": "USNYC"}).json()[0]["name"] == (
        "Port of New York"
    )


def test_search_text_cannot_become_a_query_operator(
    client: TestClient, loaded: Database[dict[str, Any]]
) -> None:
    """Regex metacharacters in user text are data, not pattern syntax."""
    response = client.get("/api/v1/ports", params={"q": ".*"})
    assert response.status_code == 200
    assert response.json() == [], "'.*' must match literally, not as a wildcard"


def test_unknown_port_is_a_404_not_a_500(
    client: TestClient, loaded: Database[dict[str, Any]]
) -> None:
    response = client.get("/api/v1/ports/NOPE")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PORT_NOT_FOUND"


def test_activity_returns_only_vessels_inside_the_radius(
    client: TestClient, loaded: Database[dict[str, Any]]
) -> None:
    response = client.get("/api/v1/ports/USNYC/activity", params={"radiusKm": 10})
    assert response.status_code == 200
    payload = response.json()

    assert payload["port"]["id"] == "USNYC"
    assert payload["radiusKm"] == 10
    assert [vessel["vessel"]["mmsi"] for vessel in payload["vessels"]] == ["366000001"]
    assert payload["vessels"][0]["distanceKm"] < 1
    assert payload["truncated"] is False


def test_activity_radius_is_bounded(client: TestClient, loaded: Database[dict[str, Any]]) -> None:
    assert (
        client.get("/api/v1/ports/USNYC/activity", params={"radiusKm": 10_000}).status_code == 422
    )
    assert client.get("/api/v1/ports/USNYC/activity", params={"radiusKm": 0}).status_code == 422


def test_dataset_status_reports_ports_configured(
    client: TestClient, loaded: Database[dict[str, Any]]
) -> None:
    assert client.get("/api/v1/dataset/status").json()["portsConfigured"] is True
