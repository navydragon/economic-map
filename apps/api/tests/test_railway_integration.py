import math
import os
from pathlib import Path
import subprocess
import sys

import httpx
import mapbox_vector_tile
from sqlalchemy import text

from app.database import get_engine


MARTIN_URL = os.getenv("MARTIN_URL", "http://127.0.0.1:3000")
SOURCE_SLUG = "ci-synthetic-railways"
EXPECTED_IDS = [100, 101, 102]
PUBLIC_FIELDS = {
    "name", "ref", "railway_type", "usage", "service", "operator",
    "electrified", "gauge",
}


def test_railway_migration_and_normalization() -> None:
    with get_engine().connect() as connection:
        assert connection.scalar(text(
            "SELECT version_num FROM alembic_version"
        )) == "0001_railway_domain"
        source = connection.execute(text("""
            SELECT id, publisher, license, url FROM public.data_sources WHERE slug = :slug
        """), {"slug": SOURCE_SLUG}).one()
        assert source.publisher == "OpenStreetMap contributors"
        assert source.license == "ODbL 1.0"
        assert source.url
        rows = connection.execute(text("""
            SELECT id, source_object_type, source_object_id, railway_type, service,
                   status, ST_SRID(geom), ST_GeometryType(geom), ST_IsValid(geom)
            FROM public.railway_segments WHERE source_id = :source_id
            ORDER BY source_object_id
        """), {"source_id": source.id}).all()
        assert [row.source_object_id for row in rows] == EXPECTED_IDS
        assert [row.railway_type for row in rows] == ["rail", "narrow_gauge", "rail"]
        assert rows[2].service == "siding"
        assert all(row.source_object_type == "way" and row.status == "active" for row in rows)
        assert all(row[6:] == (4326, "ST_LineString", True) for row in rows)
        assert connection.scalar(text("""
            SELECT count(*) FROM staging_osm.railway_lines
        """)) == 3
        assert connection.scalar(text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes WHERE schemaname = 'public'
                AND tablename = 'railway_segments'
                AND indexname = 'railway_segments_geom_gix'
                AND indexdef ILIKE '%gist%'
            )
        """)) is True
        original_ids = [row.id for row in rows]

    script = Path(__file__).resolve().parents[3] / "pipelines" / "railways" / "import_railways.py"
    subprocess.run([
        sys.executable, str(script), "normalize",
        "--source-slug", SOURCE_SLUG,
        "--source-name", "CI synthetic railway fixture",
        "--source-url", "https://github.com/navydragon/economic-map/blob/main/data/fixtures/osm/railways.osm",
        "--snapshot-at", "2026-01-01T00:00:00+00:00",
        "--retrieved-at", "2026-01-01T00:00:00+00:00",
    ], check=True)
    with get_engine().connect() as connection:
        after = connection.execute(text("""
            SELECT id FROM public.railway_segments WHERE source_id = :source_id
            ORDER BY source_object_id
        """), {"source_id": source.id}).scalars().all()
    assert after == original_ids


def test_martin_serves_canonical_railways_as_mvt() -> None:
    tilejson = httpx.get(f"{MARTIN_URL}/railway_segments", timeout=10)
    assert tilejson.status_code == 200
    assert any(layer["id"] == "railway_segments" for layer in tilejson.json()["vector_layers"])

    zoom = 8
    longitude, latitude = 37.6, 55.72
    x = int((longitude + 180) / 360 * (2**zoom))
    lat_rad = math.radians(latitude)
    y = int((1 - math.asinh(math.tan(lat_rad)) / math.pi) / 2 * (2**zoom))
    response = httpx.get(
        f"{MARTIN_URL}/railway_segments/{zoom}/{x}/{y}",
        headers={"Accept": "application/x-protobuf"},
        timeout=10,
    )
    assert response.status_code == 200
    features = mapbox_vector_tile.decode(response.content)["railway_segments"]["features"]
    assert len(features) == 3
    assert all(feature["geometry"]["type"] == "LineString" for feature in features)
    assert all(set(feature["properties"]) <= PUBLIC_FIELDS for feature in features)
    assert {feature["properties"]["railway_type"] for feature in features} == {
        "rail", "narrow_gauge"
    }
    assert any(feature["properties"].get("service") == "siding" for feature in features)
    assert any(feature["properties"].get("name") == "Synthetic Main" for feature in features)
