"""Synthetic OSM waterway import, normalization, and Martin delivery."""

import math
import os
from pathlib import Path
import subprocess
import sys

import httpx
import mapbox_vector_tile
import pytest
from sqlalchemy import text

from app.database import get_engine


MARTIN_URL = os.getenv("MARTIN_URL", "http://127.0.0.1:3000")
SOURCE_SLUG = "ci-synthetic-waterways"
EXPECTED_WAYS = set(range(100, 108)) | {118}
PUBLIC_FIELDS = {"name", "ref", "waterway_class", "boat_access", "motorboat_access",
                 "ship_access", "oneway_boat", "cemt_class", "usage", "intermittent", "tidal"}


def normalize() -> None:
    script = Path(__file__).resolve().parents[3] / "pipelines/waterways/import_waterways.py"
    subprocess.run([
        sys.executable, str(script), "normalize",
        "--source-slug", SOURCE_SLUG,
        "--source-name", "CI synthetic waterway fixture",
        "--source-url", "https://github.com/navydragon/economic-map/blob/main/data/fixtures/osm/waterways.osm",
        "--snapshot-at", "2026-01-01T00:00:00+00:00",
        "--retrieved-at", "2026-01-01T00:00:00+00:00",
    ], check=True)


def tile_coordinates(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    world = 2**zoom
    return (int((lon + 180) / 360 * world),
            int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * world))


def fixture_tiles(zoom: int) -> list[tuple[int, int]]:
    west, north = tile_coordinates(37.5, 55.74, zoom)
    east, south = tile_coordinates(37.65, 55.7, zoom)
    return [(x, y) for x in range(west, east + 1) for y in range(north, south + 1)]


def features(tile: bytes) -> list[dict]:
    return mapbox_vector_tile.decode(tile).get("waterway_segments", {}).get("features", [])


def test_waterway_schema_import_metadata_and_isolation() -> None:
    with get_engine().connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0007_waterway_domain"
        source = connection.execute(text("""
            SELECT id, publisher, license, url FROM public.data_sources WHERE slug = :slug
        """), {"slug": SOURCE_SLUG}).one()
        assert source.publisher == "OpenStreetMap contributors"
        assert source.license == "ODbL 1.0" and source.url
        rows = connection.execute(text("""
            SELECT id, source_object_type, source_object_id, name, name_en, ref,
                   waterway_class, boat_access, motorboat_access, ship_access,
                   oneway_boat, cemt_class, usage, service, width, intermittent,
                   tidal, operator, wikidata, wikipedia, status,
                   ST_SRID(geom) AS srid, ST_GeometryType(geom) AS geom_type,
                   ST_IsValid(geom) AS valid, ST_IsEmpty(geom) AS empty
            FROM public.waterway_segments WHERE source_id = :source_id
            ORDER BY source_object_id
        """), {"source_id": source.id}).all()
        assert {row.source_object_id for row in rows} == EXPECTED_WAYS
        assert len(rows) == 9
        by_way = {row.source_object_id: row for row in rows}
        assert all(row.source_object_type == "way" and row.status == "active" for row in rows)
        assert all((row.srid, row.geom_type, row.valid, row.empty) ==
                   (4326, "ST_LineString", True, False) for row in rows)
        assert by_way[100].waterway_class == "river" and by_way[100].name == "Synthetic River"
        assert by_way[101].waterway_class == "river" and by_way[101].name is None
        assert by_way[102].waterway_class == "canal"
        assert by_way[105].waterway_class == "fairway"
        assert by_way[103].cemt_class == "II"
        assert (by_way[104].boat_access, by_way[104].motorboat_access,
                by_way[104].ship_access, by_way[104].oneway_boat) == (
                    "yes", "permissive", "designated", "yes")
        assert (by_way[104].usage, by_way[104].service, by_way[104].width,
                by_way[104].operator, by_way[104].ref) == (
                    "main", "navigation", "25", "Synthetic Operator", "W-TEST")
        assert (by_way[104].name_en, by_way[104].wikidata, by_way[104].wikipedia) == (
            "Synthetic Navigation Canal", "Q123", "en:Synthetic")
        assert by_way[106].intermittent is True and by_way[107].tidal is True
        assert by_way[102].intermittent is False and by_way[102].tidal is False
        assert all(getattr(by_way[100], field) is None for field in (
            "boat_access", "motorboat_access", "ship_access", "oneway_boat",
            "cemt_class", "intermittent", "tidal"))
        assert connection.scalar(text("SELECT count(*) FROM staging_osm_waterways.waterway_lines")) == 9
        assert connection.scalar(text("SELECT count(*) FROM staging_osm_railways.railway_lines")) == 3
        assert connection.scalar(text("SELECT count(*) FROM staging_osm_roads.road_lines")) == 10
        assert connection.scalar(text("SELECT count(*) FROM staging_osm_ports.port_features")) == 8
        assert connection.scalar(text("SELECT count(*) FROM public.railway_segments")) == 3
        assert connection.scalar(text("SELECT count(*) FROM public.road_segments")) == 10
        assert connection.scalar(text("SELECT count(*) FROM public.ports")) == 8
        assert connection.scalar(text("SELECT count(*) FROM staging_osm.sentinel")) == 1
        assert connection.scalar(text("""
            SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public'
                AND tablename = 'waterway_segments' AND indexname = 'waterway_segments_geom_gix'
                AND indexdef ILIKE '%gist%')
        """)) is True
        original_ids = {row.source_object_id: row.id for row in rows}
    normalize()
    with get_engine().connect() as connection:
        assert dict(connection.execute(text("""
            SELECT source_object_id, id FROM public.waterway_segments
            WHERE source_id = :source_id
        """), {"source_id": source.id}).all()) == original_ids


def test_martin_waterway_source_and_zoom_contract() -> None:
    metadata = httpx.get(f"{MARTIN_URL}/waterway_segments", timeout=10)
    assert metadata.status_code == 200
    tilejson = metadata.json()
    assert (tilejson["minzoom"], tilejson["maxzoom"]) == (5, 14)
    assert "OpenStreetMap contributors" in tilejson["attribution"]
    assert any(layer["id"] == "waterway_segments" and set(layer["fields"]) == PUBLIC_FIELDS
               for layer in tilejson["vector_layers"])
    with get_engine().connect() as connection:
        assert connection.scalar(text("SELECT public.waterway_segments_mvt(4, 8, 5)")) == b""
        by_way = dict(connection.execute(text("""
            SELECT source_object_id, id FROM public.waterway_segments
            WHERE source_id = (SELECT id FROM public.data_sources WHERE slug = :slug)
        """), {"slug": SOURCE_SLUG}).all())
    assert httpx.get(f"{MARTIN_URL}/waterway_segments/4/8/5", timeout=10).status_code == 404
    for zoom in (5, 7, 10, 13):
        returned = {}
        for x, y in fixture_tiles(zoom):
            response = httpx.get(f"{MARTIN_URL}/waterway_segments/{zoom}/{x}/{y}",
                                 headers={"Accept": "application/x-protobuf"}, timeout=10)
            assert response.status_code in (200, 204)
            decoded = mapbox_vector_tile.decode(response.content)
            assert set(decoded) <= {"waterway_segments"}
            for feature in features(response.content):
                returned[feature["id"]] = feature
        assert set(returned) == set(by_way.values())
        assert all(feature["geometry"]["type"] in ("LineString", "MultiLineString")
                   for feature in returned.values())
        assert all(set(feature["properties"]) <= PUBLIC_FIELDS for feature in returned.values())
        assert returned[by_way[103]]["properties"]["cemt_class"] == "II"
        navigation = returned[by_way[104]]["properties"]
        assert {key: navigation[key] for key in (
            "boat_access", "motorboat_access", "ship_access", "oneway_boat", "usage"
        )} == {"boat_access": "yes", "motorboat_access": "permissive",
               "ship_access": "designated", "oneway_boat": "yes", "usage": "main"}
        assert returned[by_way[106]]["properties"]["intermittent"] is True
        assert returned[by_way[107]]["properties"]["tidal"] is True


def test_waterway_reimport_updates_and_removes_only_its_source() -> None:
    engine = get_engine()
    with engine.connect() as staging:
        with staging.begin():
            staging.execute(text("""
                CREATE TEMP TABLE waterway_stage_backup ON COMMIT PRESERVE ROWS AS
                SELECT * FROM staging_osm_waterways.waterway_lines
            """))
            staging.execute(text("""
                UPDATE staging_osm_waterways.waterway_lines
                SET name = 'Synthetic Reimport River Updated' WHERE way_id = 118
            """))
            staging.execute(text("DELETE FROM staging_osm_waterways.waterway_lines WHERE way_id = 101"))
        try:
            with engine.connect() as connection:
                original_id = connection.scalar(text("""
                    SELECT id FROM public.waterway_segments WHERE source_object_id = 118
                """))
            normalize()
            with engine.connect() as connection:
                updated = connection.execute(text("""
                    SELECT id, name FROM public.waterway_segments WHERE source_object_id = 118
                """)).one()
                assert updated.id == original_id
                assert updated.name == "Synthetic Reimport River Updated"
                assert connection.scalar(text("""
                    SELECT count(*) FROM public.waterway_segments WHERE source_object_id = 101
                """)) == 0
                assert connection.scalar(text("SELECT count(*) FROM public.ports")) == 8
                assert connection.scalar(text("SELECT count(*) FROM public.road_segments")) == 10
                assert connection.scalar(text("SELECT count(*) FROM public.railway_segments")) == 3
        finally:
            with staging.begin():
                staging.execute(text("TRUNCATE staging_osm_waterways.waterway_lines"))
                staging.execute(text("INSERT INTO staging_osm_waterways.waterway_lines SELECT * FROM waterway_stage_backup"))
                staging.execute(text("DROP TABLE waterway_stage_backup"))
            normalize()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM public.waterway_segments")) == 9
        assert connection.scalar(text("""
            SELECT name FROM public.waterway_segments WHERE source_object_id = 118
        """)) == "Synthetic Reimport River"


@pytest.mark.parametrize("zoom", [7, 11])
def test_waterway_mvt_buffer_includes_near_line_only(zoom: int) -> None:
    x, y = tile_coordinates(-90, 30, zoom)
    insert_sql = text("""
        WITH bounds AS (SELECT ST_TileEnvelope(:z, :x, :y) AS tile)
        INSERT INTO public.waterway_segments
            (source_id, source_object_type, source_object_id, waterway_class, geom)
        SELECT (SELECT id FROM public.data_sources WHERE slug = :slug),
            'way', :object_id, 'river',
            ST_Transform(ST_MakeLine(
                ST_SetSRID(ST_MakePoint(
                    ST_XMin(tile) - (ST_XMax(tile) - ST_XMin(tile)) * :offset / 4096.0,
                    ST_YMin(tile) + (ST_YMax(tile) - ST_YMin(tile)) * 0.4), 3857),
                ST_SetSRID(ST_MakePoint(
                    ST_XMin(tile) - (ST_XMax(tile) - ST_XMin(tile)) * :offset / 4096.0,
                    ST_YMin(tile) + (ST_YMax(tile) - ST_YMin(tile)) * 0.6), 3857)
            ), 4326)
        FROM bounds RETURNING id
    """)
    bounds_sql = text("""
        SELECT geom && ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326),
               geom && ST_Transform(
                   ST_TileEnvelope(:z, :x, :y, margin => 64.0 / 4096.0), 4326)
        FROM public.waterway_segments WHERE id = :id
    """)
    with get_engine().connect() as connection:
        transaction = connection.begin()
        try:
            params = {"z": zoom, "x": x, "y": y, "slug": SOURCE_SLUG}
            near = connection.scalar(insert_sql, {**params, "object_id": -1, "offset": 32})
            far = connection.scalar(insert_sql, {**params, "object_id": -2, "offset": 96})
            assert tuple(connection.execute(bounds_sql, {**params, "id": near}).one()) == (False, True)
            assert tuple(connection.execute(bounds_sql, {**params, "id": far}).one()) == (False, False)
            returned = {feature["id"] for feature in features(connection.scalar(text(
                "SELECT public.waterway_segments_mvt(:z, :x, :y)"), params))}
            assert near in returned and far not in returned
        finally:
            transaction.rollback()
