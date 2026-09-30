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
SOURCE_SLUG = "ci-synthetic-roads"
EXPECTED_WAY_IDS = list(range(100, 110))
PUBLIC_FIELDS = {
    "name", "ref", "road_class", "is_link", "surface", "lanes", "maxspeed",
    "oneway", "access", "toll", "bridge", "tunnel", "operator", "network",
}


def run_normalization() -> None:
    script = Path(__file__).resolve().parents[3] / "pipelines" / "roads" / "import_roads.py"
    subprocess.run([
        sys.executable, str(script), "normalize",
        "--source-slug", SOURCE_SLUG,
        "--source-name", "CI synthetic road fixture",
        "--source-url", "https://github.com/navydragon/economic-map/blob/main/data/fixtures/osm/roads.osm",
        "--snapshot-at", "2026-01-01T00:00:00+00:00",
        "--retrieved-at", "2026-01-01T00:00:00+00:00",
    ], check=True)


def tile_coordinates(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    x = int((lon + 180) / 360 * (2**zoom))
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * (2**zoom))
    return x, y


def fixture_tiles(zoom: int) -> list[tuple[int, int]]:
    west, south, east, north = 37.5, 55.7, 37.65, 55.718
    min_x, min_y = tile_coordinates(west, north, zoom)
    max_x, max_y = tile_coordinates(east, south, zoom)
    return [(x, y) for x in range(min_x, max_x + 1)
            for y in range(min_y, max_y + 1)]


def decoded_features(tile: bytes) -> list[dict]:
    return mapbox_vector_tile.decode(tile).get("road_segments", {}).get("features", [])


def test_road_schema_import_normalization_and_isolation() -> None:
    with get_engine().connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0004_road_domain"
        source = connection.execute(text("""
            SELECT id, publisher, license, url FROM public.data_sources WHERE slug = :slug
        """), {"slug": SOURCE_SLUG}).one()
        assert source.publisher == "OpenStreetMap contributors"
        assert source.license == "ODbL 1.0"
        assert source.url
        rows = connection.execute(text("""
            SELECT id, source_object_type, source_object_id, road_class, is_link,
                   name, ref, surface, lanes, maxspeed, oneway, bridge, tunnel,
                   status, ST_SRID(geom), ST_GeometryType(geom), ST_IsValid(geom)
            FROM public.road_segments WHERE source_id = :source_id
            ORDER BY source_object_id
        """), {"source_id": source.id}).all()
        assert [row.source_object_id for row in rows] == EXPECTED_WAY_IDS
        assert [row.road_class for row in rows] == [
            road_class for road_class in ("motorway", "trunk", "primary", "secondary", "tertiary")
            for _ in (False, True)
        ]
        assert [row.is_link for row in rows] == [False, True] * 5
        assert all(row.source_object_type == "way" and row.status == "active" for row in rows)
        assert all(row[14:] == (4326, "ST_LineString", True) for row in rows)
        assert rows[0].name == "Synthetic Motorway"
        assert (rows[0].ref, rows[0].surface, rows[0].lanes, rows[0].maxspeed,
                rows[0].oneway) == ("M-TEST", "asphalt", "4", "110", "yes")
        assert rows[2].bridge == "yes"
        assert rows[6].tunnel == "yes"
        assert connection.scalar(text("SELECT count(*) FROM staging_osm_roads.road_lines")) == 10
        assert connection.scalar(text("SELECT count(*) FROM staging_osm_railways.railway_lines")) == 3
        assert connection.scalar(text("SELECT count(*) FROM public.railway_segments")) == 3
        assert connection.scalar(text("SELECT count(*) FROM staging_osm.sentinel")) == 1
        assert connection.scalar(text("""
            SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public'
                AND tablename = 'road_segments' AND indexname = 'road_segments_geom_gix'
                AND indexdef ILIKE '%gist%')
        """)) is True
        original_ids = [row.id for row in rows]

    run_normalization()
    with get_engine().connect() as connection:
        after = connection.execute(text("""
            SELECT id FROM public.road_segments WHERE source_id = :source_id
            ORDER BY source_object_id
        """), {"source_id": source.id}).scalars().all()
    assert after == original_ids


def test_martin_serves_road_zoom_hierarchy() -> None:
    tilejson = httpx.get(f"{MARTIN_URL}/road_segments", timeout=10)
    assert tilejson.status_code == 200
    metadata = tilejson.json()
    assert metadata["minzoom"] == 5 and metadata["maxzoom"] == 14
    assert "OpenStreetMap contributors" in metadata["attribution"]
    assert any(layer["id"] == "road_segments" and set(layer["fields"]) == PUBLIC_FIELDS
               for layer in metadata["vector_layers"])

    with get_engine().connect() as connection:
        way_to_id = dict(connection.execute(text("""
            SELECT source_object_id, id FROM public.road_segments
            WHERE source_id = (SELECT id FROM public.data_sources WHERE slug = :slug)
        """), {"slug": SOURCE_SLUG}).all())
        assert len(way_to_id) == 10
        empty = connection.scalar(text("SELECT public.road_segments_mvt(4, 8, 5)"))
        assert empty == b"" and decoded_features(empty) == []

    expected_by_zoom = {
        5: {100, 102},
        6: {100, 102, 104},
        7: {100, 102, 104, 106},
        8: {100, 102, 104, 106, 108},
        9: {100, 102, 104, 106, 108},
        10: set(EXPECTED_WAY_IDS),
    }
    for zoom, expected_ways in expected_by_zoom.items():
        features_by_id = {}
        for x, y in fixture_tiles(zoom):
            response = httpx.get(
                f"{MARTIN_URL}/road_segments/{zoom}/{x}/{y}",
                headers={"Accept": "application/x-protobuf"}, timeout=10,
            )
            assert response.status_code in (200, 204)
            for feature in decoded_features(response.content):
                features_by_id[feature["id"]] = feature
        assert set(features_by_id) == {way_to_id[way_id] for way_id in expected_ways}
        assert all(feature["geometry"]["type"] == "LineString"
                   for feature in features_by_id.values())
        assert all(set(feature["properties"]) <= PUBLIC_FIELDS
                   for feature in features_by_id.values())
        assert all(feature["properties"]["is_link"] == (way_id % 2 == 1)
                   for way_id in expected_ways
                   for feature in [features_by_id[way_to_id[way_id]]])
    with get_engine().connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM public.road_segments")) == 10


def test_road_reimport_updates_attributes_and_removes_missing_ways() -> None:
    engine = get_engine()
    with engine.connect() as staging_connection:
        with staging_connection.begin():
            staging_connection.execute(text("""
                CREATE TEMP TABLE road_stage_backup ON COMMIT PRESERVE ROWS AS
                SELECT * FROM staging_osm_roads.road_lines
            """))
            staging_connection.execute(text("""
                UPDATE staging_osm_roads.road_lines
                SET name = 'Synthetic Motorway Updated' WHERE way_id = 100
            """))
            staging_connection.execute(text("""
                DELETE FROM staging_osm_roads.road_lines WHERE way_id = 104
            """))
        try:
            with engine.connect() as connection:
                original_id = connection.scalar(text("""
                    SELECT id FROM public.road_segments
                    WHERE source_id = (SELECT id FROM public.data_sources WHERE slug = :slug)
                      AND source_object_id = 100
                """), {"slug": SOURCE_SLUG})
            run_normalization()
            with engine.connect() as connection:
                rows = connection.execute(text("""
                    SELECT id, source_object_id, name FROM public.road_segments
                    WHERE source_id = (SELECT id FROM public.data_sources WHERE slug = :slug)
                    ORDER BY source_object_id
                """), {"slug": SOURCE_SLUG}).all()
            assert [row.source_object_id for row in rows] == [way for way in EXPECTED_WAY_IDS if way != 104]
            assert rows[0].id == original_id
            assert rows[0].name == "Synthetic Motorway Updated"
        finally:
            with staging_connection.begin():
                staging_connection.execute(text("TRUNCATE staging_osm_roads.road_lines"))
                staging_connection.execute(text("""
                    INSERT INTO staging_osm_roads.road_lines SELECT * FROM road_stage_backup
                """))
                staging_connection.execute(text("DROP TABLE road_stage_backup"))
            run_normalization()
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT source_object_id, name FROM public.road_segments
            WHERE source_id = (SELECT id FROM public.data_sources WHERE slug = :slug)
            ORDER BY source_object_id
        """), {"slug": SOURCE_SLUG}).all()
    assert [row.source_object_id for row in rows] == EXPECTED_WAY_IDS
    assert rows[0].name == "Synthetic Motorway"


def test_road_mvt_respects_tile_buffer() -> None:
    zoom, x, y = 11, 1200, 700
    insert_sql = text("""
        WITH bounds AS (SELECT ST_TileEnvelope(:z, :x, :y) AS tile)
        INSERT INTO public.road_segments
            (source_id, source_object_type, source_object_id, road_class, is_link, geom)
        SELECT
            (SELECT id FROM public.data_sources WHERE slug = :source_slug),
            'way', :object_id, 'primary', false,
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
        FROM bounds RETURNING id
    """)
    bounds_sql = text("""
        SELECT
            r.geom && ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326),
            r.geom && ST_Transform(
                ST_TileEnvelope(:z, :x, :y, margin => 64.0 / 4096.0), 4326)
        FROM public.road_segments AS r WHERE r.id = :id
    """)
    with get_engine().connect() as connection:
        transaction = connection.begin()
        try:
            params = {"z": zoom, "x": x, "y": y, "source_slug": SOURCE_SLUG}
            near_id = connection.execute(insert_sql, {
                **params, "object_id": -1, "offset_units": 32,
            }).scalar_one()
            far_id = connection.execute(insert_sql, {
                **params, "object_id": -2, "offset_units": 96,
            }).scalar_one()
            assert tuple(connection.execute(bounds_sql, {**params, "id": near_id}).one()) == (False, True)
            assert tuple(connection.execute(bounds_sql, {**params, "id": far_id}).one()) == (False, False)
            tile = connection.scalar(text("""
                SELECT public.road_segments_mvt(:z, :x, :y)
            """), params)
            features = {feature["id"]: feature for feature in decoded_features(tile)}
            assert near_id in features and far_id not in features
            assert features[near_id]["geometry"]["type"] == "LineString"
        finally:
            transaction.rollback()
