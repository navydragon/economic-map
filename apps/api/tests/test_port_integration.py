"""Synthetic end-to-end civilian port import and Martin delivery."""

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
SOURCE_SLUG = "ci-synthetic-ports"
EXPECTED_OBJECTS = {
    ("node", 100), ("node", 101), ("node", 102), ("node", 103),
    ("node", 200), ("way", 200), ("way", 201), ("relation", 300),
}
PUBLIC_FIELDS = {"name", "facility_class", "water_context", "cargo",
                 "operator", "access", "status"}


def normalize() -> None:
    script = Path(__file__).resolve().parents[3] / "pipelines/ports/import_ports.py"
    subprocess.run([
        sys.executable, str(script), "normalize",
        "--source-slug", SOURCE_SLUG,
        "--source-name", "CI synthetic port fixture",
        "--source-url", "https://github.com/navydragon/economic-map/blob/main/data/fixtures/osm/ports.osm",
        "--snapshot-at", "2026-01-01T00:00:00+00:00",
        "--retrieved-at", "2026-01-01T00:00:00+00:00",
    ], check=True)


def tile_coordinates(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    x = int((lon + 180) / 360 * 2**zoom)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2**zoom)
    return x, y


def fixture_tiles(zoom: int) -> list[tuple[int, int]]:
    min_x, min_y = tile_coordinates(37.49, 55.75, zoom)
    max_x, max_y = tile_coordinates(37.65, 55.69, zoom)
    return [(x, y) for x in range(min_x, max_x + 1)
            for y in range(min_y, max_y + 1)]


def features(tile: bytes) -> list[dict]:
    return mapbox_vector_tile.decode(tile).get("ports", {}).get("features", [])


def test_port_schema_import_isolation_and_idempotency() -> None:
    with get_engine().connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0008_waterway_mvt_aggregation"
        source = connection.execute(text("""
            SELECT id, publisher, license, url FROM public.data_sources WHERE slug = :slug
        """), {"slug": SOURCE_SLUG}).one()
        assert source.publisher == "OpenStreetMap contributors"
        assert source.license == "ODbL 1.0" and source.url
        rows = connection.execute(text("""
            SELECT id, source_object_type, source_object_id, facility_class,
                   water_context, name, ST_SRID(geom) AS srid,
                   ST_GeometryType(geom) AS geometry_type, ST_IsValid(geom) AS valid
            FROM public.ports WHERE source_id = :source_id
            ORDER BY source_object_type, source_object_id
        """), {"source_id": source.id}).all()
        assert {(row.source_object_type, row.source_object_id) for row in rows} == EXPECTED_OBJECTS
        by_object = {(row.source_object_type, row.source_object_id): row for row in rows}
        assert by_object["node", 100].facility_class == "commercial_port"
        assert by_object["node", 102].facility_class == "fishing_port"
        assert by_object["node", 103].facility_class == "cargo_terminal"
        assert by_object["way", 200].facility_class == "cargo_terminal"
        assert by_object["way", 201].facility_class == "commercial_port"
        assert by_object["way", 201].water_context == "sea"
        assert by_object["relation", 300].facility_class == "port"
        assert by_object["relation", 300].water_context is None
        assert by_object["node", 101].name is None
        assert by_object["node", 200].id != by_object["way", 200].id
        assert all((row.srid, row.geometry_type, row.valid) == (4326, "ST_Point", True)
                   for row in rows)
        assert connection.scalar(text("SELECT count(*) FROM staging_osm_ports.port_features")) == 8
        assert connection.scalar(text("SELECT count(*) FROM staging_osm_roads.road_lines")) == 10
        assert connection.scalar(text("SELECT count(*) FROM staging_osm_railways.railway_lines")) == 3
        assert connection.scalar(text("SELECT count(*) FROM public.road_segments")) == 10
        assert connection.scalar(text("SELECT count(*) FROM public.railway_segments")) == 3
        assert connection.scalar(text("SELECT count(*) FROM staging_osm.sentinel")) == 1
        assert connection.scalar(text("""
            SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public'
                AND tablename = 'ports' AND indexname = 'ports_geom_gix'
                AND indexdef ILIKE '%gist%')
        """)) is True
        assert connection.scalar(text("""
            SELECT ST_Equals(p.geom, ST_PointOnSurface(s.geom))
            FROM public.ports p JOIN staging_osm_ports.port_features s
              ON s.osm_type = 'W' AND s.osm_id = p.source_object_id
            WHERE p.source_id = :source_id AND p.source_object_type = 'way'
              AND p.source_object_id = 200
        """), {"source_id": source.id}) is True
        original_ids = {(row.source_object_type, row.source_object_id): row.id for row in rows}
    normalize()
    with get_engine().connect() as connection:
        repeated = connection.execute(text("""
            SELECT source_object_type, source_object_id, id FROM public.ports WHERE source_id = :source_id
        """), {"source_id": source.id}).all()
    assert {(row.source_object_type, row.source_object_id): row.id for row in repeated} == original_ids


def test_martin_port_zoom_and_public_contract() -> None:
    metadata = httpx.get(f"{MARTIN_URL}/ports", timeout=10)
    assert metadata.status_code == 200
    tilejson = metadata.json()
    assert (tilejson["minzoom"], tilejson["maxzoom"]) == (5, 14)
    assert "OpenStreetMap contributors" in tilejson["attribution"]
    assert any(layer["id"] == "ports" and set(layer["fields"]) == PUBLIC_FIELDS
               for layer in tilejson["vector_layers"])
    with get_engine().connect() as connection:
        assert connection.scalar(text("SELECT public.ports_mvt(4, 8, 5)")) == b""
        canonical = connection.execute(text("""
            SELECT id, source_object_type, source_object_id, name, facility_class
            FROM public.ports WHERE source_id =
                (SELECT id FROM public.data_sources WHERE slug = :slug)
        """), {"slug": SOURCE_SLUG}).all()
    assert httpx.get(f"{MARTIN_URL}/ports/4/8/5", timeout=10).status_code == 404
    named_ids = {row.id for row in canonical if row.name}
    all_ids = {row.id for row in canonical}
    for zoom, expected in ((5, named_ids), (6, named_ids), (7, all_ids), (10, all_ids)):
        returned = {}
        for x, y in fixture_tiles(zoom):
            response = httpx.get(f"{MARTIN_URL}/ports/{zoom}/{x}/{y}",
                                 headers={"Accept": "application/x-protobuf"}, timeout=10)
            assert response.status_code in (200, 204)
            for feature in features(response.content):
                returned[feature["id"]] = feature
        assert set(returned) == expected
        assert all(feature["geometry"]["type"] == "Point" for feature in returned.values())
        assert all(set(feature["properties"]) <= PUBLIC_FIELDS for feature in returned.values())
        assert all(feature["properties"]["facility_class"] in
                   {"commercial_port", "cargo_terminal", "fishing_port", "port"}
                   for feature in returned.values())


def test_port_reimport_updates_and_removes_only_its_source() -> None:
    engine = get_engine()
    with engine.connect() as staging:
        with staging.begin():
            staging.execute(text("CREATE TEMP TABLE port_stage_backup ON COMMIT PRESERVE ROWS AS SELECT * FROM staging_osm_ports.port_features"))
            staging.execute(text("UPDATE staging_osm_ports.port_features SET name = 'Synthetic Trade Harbour Updated' WHERE osm_type = 'N' AND osm_id = 100"))
            staging.execute(text("DELETE FROM staging_osm_ports.port_features WHERE osm_type = 'W' AND osm_id = 201"))
        try:
            with engine.connect() as connection:
                before = connection.scalar(text("""
                    SELECT id FROM public.ports WHERE source_object_type = 'node'
                    AND source_object_id = 100
                """))
            normalize()
            with engine.connect() as connection:
                after = connection.execute(text("""
                    SELECT id, name FROM public.ports WHERE source_object_type = 'node'
                    AND source_object_id = 100
                """)).one()
                assert after.id == before and after.name == "Synthetic Trade Harbour Updated"
                assert connection.scalar(text("""
                    SELECT count(*) FROM public.ports WHERE source_object_type = 'way'
                    AND source_object_id = 201
                """)) == 0
                assert connection.scalar(text("SELECT count(*) FROM public.road_segments")) == 10
                assert connection.scalar(text("SELECT count(*) FROM public.railway_segments")) == 3
        finally:
            with staging.begin():
                staging.execute(text("TRUNCATE staging_osm_ports.port_features"))
                staging.execute(text("INSERT INTO staging_osm_ports.port_features SELECT * FROM port_stage_backup"))
                staging.execute(text("DROP TABLE port_stage_backup"))
            normalize()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM public.ports")) == 8
        assert connection.scalar(text("""
            SELECT name FROM public.ports WHERE source_object_type = 'node' AND source_object_id = 100
        """)) == "Synthetic Trade Harbour"


def test_port_mvt_buffer_includes_near_point_only() -> None:
    zoom, x, y = 11, 1200, 700
    insert_sql = text("""
        WITH bounds AS (SELECT ST_TileEnvelope(:z, :x, :y) AS tile)
        INSERT INTO public.ports
            (source_id, source_object_type, source_object_id, facility_class, geom)
        SELECT (SELECT id FROM public.data_sources WHERE slug = :slug),
            'node', :object_id, 'port',
            ST_Transform(ST_SetSRID(ST_MakePoint(
                ST_XMin(tile) - (ST_XMax(tile) - ST_XMin(tile)) * :offset / 4096.0,
                ST_YMin(tile) + (ST_YMax(tile) - ST_YMin(tile)) * 0.5
            ), 3857), 4326)
        FROM bounds RETURNING id
    """)
    with get_engine().connect() as connection:
        transaction = connection.begin()
        try:
            params = {"z": zoom, "x": x, "y": y, "slug": SOURCE_SLUG}
            near = connection.scalar(insert_sql, {**params, "object_id": -1, "offset": 32})
            far = connection.scalar(insert_sql, {**params, "object_id": -2, "offset": 96})
            assert connection.scalar(text("""
                SELECT geom && ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326)
                FROM public.ports WHERE id = :id
            """), {**params, "id": near}) is False
            tile = connection.scalar(text("SELECT public.ports_mvt(:z, :x, :y)"), params)
            returned = {feature["id"] for feature in features(tile)}
            assert near in returned and far not in returned
        finally:
            transaction.rollback()
