import os

import httpx
import mapbox_vector_tile
import pytest
from sqlalchemy import text

from app.database import get_engine

MARTIN_URL = os.getenv("MARTIN_URL", "http://127.0.0.1:3000")
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")

EXPECTED_SITES = [
    (1, "Synthetic Site A", "demo", 10, 37.6, 55.8),
    (2, "Synthetic Site B", "demo", 20, 60.6, 56.8),
    (3, "Synthetic Site C", "demo", 30, 92.9, 56.0),
    (4, "Synthetic Site D", "demo", 40, 129.7, 62.0),
    (5, "Synthetic Site E", "demo", 50, 131.9, 43.1),
]


def test_postgis_fixture() -> None:
    with get_engine().connect() as connection:
        assert connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'"))
        assert connection.scalar(text("SELECT PostGIS_Version()"))
        rows = connection.execute(
            text(
                "SELECT id, name, category, value, ST_X(geom), ST_Y(geom), "
                "ST_IsValid(geom), ST_SRID(geom), ST_GeometryType(geom) "
                "FROM public.demo_sites ORDER BY id"
            )
        ).all()
        index_exists = connection.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename = 'demo_sites' "
                "AND indexname = 'demo_sites_geom_gix')"
            )
        )

    assert len(rows) == len(EXPECTED_SITES)
    assert index_exists is True
    for row, expected in zip(rows, EXPECTED_SITES, strict=True):
        assert tuple(row[:4]) == expected[:4]
        assert row[4] == pytest.approx(expected[4])
        assert row[5] == pytest.approx(expected[5])
        assert row[6] is True
        assert row[7] == 4326
        assert row[8] == "ST_Point"


def test_martin_serves_demo_sites_as_mvt() -> None:
    tilejson = httpx.get(f"{MARTIN_URL}/demo_sites", timeout=10)
    assert tilejson.status_code == 200
    assert any(layer["id"] == "demo_sites" for layer in tilejson.json()["vector_layers"])

    response = httpx.get(
        f"{MARTIN_URL}/demo_sites/0/0/0",
        headers={"Accept": "application/x-protobuf"},
        timeout=10,
    )
    assert response.status_code == 200
    assert response.content

    tile = mapbox_vector_tile.decode(response.content)
    features = tile["demo_sites"]["features"]
    assert sorted(feature["id"] for feature in features) == [1, 2, 3, 4, 5]
    assert all(feature["geometry"]["type"] == "Point" for feature in features)
    assert {feature["properties"]["name"] for feature in features} == {
        site[1] for site in EXPECTED_SITES
    }
    assert sorted(feature["properties"]["value"] for feature in features) == [
        10, 20, 30, 40, 50
    ]


def test_api_connects_to_postgis() -> None:
    health = httpx.get(f"{API_URL}/health", timeout=10)
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    database_health = httpx.get(f"{API_URL}/health/db", timeout=10)
    assert database_health.status_code == 200
    payload = database_health.json()
    assert payload["status"] == "ok"
    assert payload["postgis_version"]
