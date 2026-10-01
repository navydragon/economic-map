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
FIXTURE_BOUNDS = (37.5, 55.7, 37.7, 55.75)


def tile_coordinates(longitude: float, latitude: float, zoom: int) -> tuple[int, int]:
    x = int((longitude + 180) / 360 * (2**zoom))
    lat_rad = math.radians(latitude)
    y = int((1 - math.asinh(math.tan(lat_rad)) / math.pi) / 2 * (2**zoom))
    return x, y


def fixture_tiles(zoom: int) -> list[tuple[int, int]]:
    west, south, east, north = FIXTURE_BOUNDS
    min_x, min_y = tile_coordinates(west, north, zoom)
    max_x, max_y = tile_coordinates(east, south, zoom)
    return [(x, y) for x in range(min_x, max_x + 1)
            for y in range(min_y, max_y + 1)]


def decoded_features(tile: bytes) -> list[dict]:
    return mapbox_vector_tile.decode(tile).get("railway_segments", {}).get("features", [])


def run_normalization() -> None:
    script = Path(__file__).resolve().parents[3] / "pipelines" / "railways" / "import_railways.py"
    subprocess.run([
        sys.executable, str(script), "normalize",
        "--source-slug", SOURCE_SLUG,
        "--source-name", "CI synthetic railway fixture",
        "--source-url", "https://github.com/navydragon/economic-map/blob/main/data/fixtures/osm/railways.osm",
        "--snapshot-at", "2026-01-01T00:00:00+00:00",
        "--retrieved-at", "2026-01-01T00:00:00+00:00",
    ], check=True)


def test_railway_migration_and_normalization() -> None:
    with get_engine().connect() as connection:
        assert connection.scalar(text(
            "SELECT version_num FROM alembic_version"
        )) == "0006_port_domain"
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
            SELECT count(*) FROM staging_osm_railways.railway_lines
        """)) == 3
        assert connection.scalar(text("SELECT count(*) FROM staging_osm.sentinel")) == 1
        assert connection.scalar(text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes WHERE schemaname = 'public'
                AND tablename = 'railway_segments'
                AND indexname = 'railway_segments_geom_gix'
                AND indexdef ILIKE '%gist%'
            )
        """)) is True
        original_ids = [row.id for row in rows]

    run_normalization()
    with get_engine().connect() as connection:
        after = connection.execute(text("""
            SELECT id FROM public.railway_segments WHERE source_id = :source_id
            ORDER BY source_object_id
        """), {"source_id": source.id}).scalars().all()
    assert after == original_ids


def test_martin_serves_zoom_aware_railways_as_mvt() -> None:
    tilejson = httpx.get(f"{MARTIN_URL}/railway_segments", timeout=10)
    assert tilejson.status_code == 200
    metadata = tilejson.json()
    assert metadata["minzoom"] == 5
    assert metadata["maxzoom"] == 14
    assert "OpenStreetMap contributors" in metadata["attribution"]
    assert any(layer["id"] == "railway_segments" and
               set(layer["fields"]) == PUBLIC_FIELDS
               for layer in metadata["vector_layers"])

    for zoom, expected_count, expect_service in [
        (5, 2, False), (8, 2, False), (10, 2, False), (11, 3, True)
    ]:
        features_by_id = {}
        for x, y in fixture_tiles(zoom):
            response = httpx.get(
                f"{MARTIN_URL}/railway_segments/{zoom}/{x}/{y}",
                headers={"Accept": "application/x-protobuf"},
                timeout=10,
            )
            assert response.status_code in (200, 204)
            for feature in decoded_features(response.content):
                features_by_id[feature["id"]] = feature

        assert len(features_by_id) == expected_count
        features = list(features_by_id.values())
        assert all(feature["geometry"]["type"] == "LineString" for feature in features)
        assert all(set(feature["properties"]) <= PUBLIC_FIELDS for feature in features)
        assert {feature["properties"]["railway_type"] for feature in features} == {
            "rail", "narrow_gauge"
        }
        assert any(feature["properties"].get("service") == "siding" for feature in features) == expect_service
        assert any(feature["properties"].get("name") == "Synthetic Main" for feature in features)


def test_railway_mvt_function_filters_without_removing_canonical_rows() -> None:
    with get_engine().connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM public.railway_segments")) == 3
        empty = connection.scalar(text("SELECT public.railway_segments_mvt(4, 8, 5)"))
        assert empty == b""
        assert decoded_features(empty) == []
        for zoom, expected_count in [(5, 2), (8, 2), (10, 2), (11, 3)]:
            features_by_id = {}
            for x, y in fixture_tiles(zoom):
                tile = connection.scalar(text("""
                    SELECT public.railway_segments_mvt(:z, :x, :y)
                """), {"z": zoom, "x": x, "y": y})
                for feature in decoded_features(tile):
                    features_by_id[feature["id"]] = feature
            assert len(features_by_id) == expected_count
            assert (any(feature["properties"].get("service") == "siding"
                        for feature in features_by_id.values())) == (zoom >= 11)
        assert connection.scalar(text("SELECT count(*) FROM public.railway_segments")) == 3


def test_railway_mvt_includes_geometry_within_tile_buffer() -> None:
    zoom, x, y = 11, 1200, 700
    insert_sql = text("""
        WITH bounds AS (SELECT ST_TileEnvelope(:z, :x, :y) AS tile)
        INSERT INTO public.railway_segments
            (source_id, source_object_type, source_object_id, name, railway_type, geom)
        SELECT
            (SELECT id FROM public.data_sources WHERE slug = :source_slug),
            'way', :object_id, :name, 'rail',
            ST_Transform(ST_MakeLine(
                ST_SetSRID(ST_MakePoint(
                    ST_XMin(tile) - (ST_XMax(tile) - ST_XMin(tile)) * :offset_units / 4096.0,
                    ST_YMin(tile) + (ST_YMax(tile) - ST_YMin(tile)) * 0.4
                ), 3857),
                ST_SetSRID(ST_MakePoint(
                    ST_XMin(tile) - (ST_XMax(tile) - ST_XMin(tile)) * :offset_units / 4096.0,
                    ST_YMin(tile) + (ST_YMax(tile) - ST_YMin(tile)) * 0.6
                ), 3857)
            ), 4326)
        FROM bounds
        RETURNING id
    """)
    bounds_sql = text("""
        SELECT
            r.geom && ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326) AS in_tile,
            r.geom && ST_Transform(
                ST_TileEnvelope(:z, :x, :y, margin => 64.0 / 4096.0), 4326
            ) AS in_query_buffer
        FROM public.railway_segments AS r WHERE r.id = :id
    """)

    with get_engine().connect() as connection:
        transaction = connection.begin()
        try:
            parameters = {"z": zoom, "x": x, "y": y, "source_slug": SOURCE_SLUG}
            near_id = connection.execute(insert_sql, {
                **parameters, "object_id": -1, "name": "Buffered edge near",
                "offset_units": 32,
            }).scalar_one()
            far_id = connection.execute(insert_sql, {
                **parameters, "object_id": -2, "name": "Buffered edge far",
                "offset_units": 96,
            }).scalar_one()

            assert tuple(connection.execute(bounds_sql, {**parameters, "id": near_id}).one()) == (
                False, True
            )
            assert tuple(connection.execute(bounds_sql, {**parameters, "id": far_id}).one()) == (
                False, False
            )

            tile = connection.scalar(text("""
                SELECT public.railway_segments_mvt(:z, :x, :y)
            """), parameters)
            features = {feature["id"]: feature for feature in decoded_features(tile)}
            assert near_id in features
            assert features[near_id]["geometry"]["type"] == "LineString"
            assert far_id not in features
        finally:
            transaction.rollback()


def test_reimport_updates_attributes_and_removes_missing_ways() -> None:
    engine = get_engine()
    with engine.connect() as staging_connection:
        with staging_connection.begin():
            staging_connection.execute(text("""
                CREATE TEMP TABLE railway_stage_backup ON COMMIT PRESERVE ROWS AS
                SELECT * FROM staging_osm_railways.railway_lines
            """))
            staging_connection.execute(text("""
                UPDATE staging_osm_railways.railway_lines
                SET name = 'Synthetic Main Updated' WHERE way_id = 100
            """))
            staging_connection.execute(text("""
                DELETE FROM staging_osm_railways.railway_lines WHERE way_id = 101
            """))

        try:
            with engine.connect() as connection:
                original_id = connection.scalar(text("""
                    SELECT id FROM public.railway_segments
                    WHERE source_id = (SELECT id FROM public.data_sources WHERE slug = :slug)
                      AND source_object_type = 'way' AND source_object_id = 100
                """), {"slug": SOURCE_SLUG})
            run_normalization()
            with engine.connect() as connection:
                rows = connection.execute(text("""
                    SELECT id, source_object_id, name FROM public.railway_segments
                    WHERE source_id = (SELECT id FROM public.data_sources WHERE slug = :slug)
                    ORDER BY source_object_id
                """), {"slug": SOURCE_SLUG}).all()
            assert [row.source_object_id for row in rows] == [100, 102]
            assert rows[0].id == original_id
            assert rows[0].name == "Synthetic Main Updated"
        finally:
            with staging_connection.begin():
                staging_connection.execute(text("TRUNCATE staging_osm_railways.railway_lines"))
                staging_connection.execute(text("""
                    INSERT INTO staging_osm_railways.railway_lines
                    SELECT * FROM railway_stage_backup
                """))
                staging_connection.execute(text("DROP TABLE railway_stage_backup"))
            run_normalization()
    with engine.connect() as connection:
        restored = connection.execute(text("""
            SELECT source_object_id, name FROM public.railway_segments
            WHERE source_id = (SELECT id FROM public.data_sources WHERE slug = :slug)
            ORDER BY source_object_id
        """), {"slug": SOURCE_SLUG}).all()
    assert [row.source_object_id for row in restored] == EXPECTED_IDS
    assert restored[0].name == "Synthetic Main"
