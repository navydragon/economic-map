"""Import an explicit local OSM extract, then normalize major road ways."""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import time

from sqlalchemy import URL, create_engine, text


REPO_ROOT = Path(__file__).resolve().parents[2]


def aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("timestamp must be ISO 8601") from error
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed


def database_url() -> URL:
    password = os.environ.get("POSTGRES_PASSWORD")
    if not password:
        raise SystemExit("POSTGRES_PASSWORD must be set (for example via uv --env-file)")
    return URL.create(
        "postgresql+psycopg",
        username=os.environ.get("POSTGRES_USER", "russia_map"),
        password=password,
        host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=os.environ.get("POSTGRES_DB", "russia_map"),
    )


def normalize(args: argparse.Namespace) -> int:
    engine = create_engine(database_url())
    with engine.begin() as connection:
        count, invalid, duplicate_ids = connection.execute(text("""
            SELECT count(*),
                count(*) FILTER (WHERE highway NOT IN (
                    'motorway', 'motorway_link', 'trunk', 'trunk_link',
                    'primary', 'primary_link', 'secondary', 'secondary_link',
                    'tertiary', 'tertiary_link'
                ) OR highway IS NULL OR geom IS NULL OR ST_IsEmpty(geom)
                  OR NOT ST_IsValid(geom) OR ST_SRID(geom) <> 4326
                  OR ST_GeometryType(geom) <> 'ST_LineString' OR ST_NPoints(geom) < 2),
                count(*) - count(DISTINCT way_id)
            FROM staging_osm_roads.road_lines
        """)).one()
        if count == 0 or invalid or duplicate_ids:
            raise ValueError(
                f"Staging validation failed: rows={count}, invalid={invalid}, duplicate_ids={duplicate_ids}"
            )

        source_id = connection.execute(text("""
            INSERT INTO public.data_sources
                (slug, name, publisher, url, license, snapshot_at, retrieved_at, description)
            VALUES
                (:slug, :name, :publisher, :url, :license, :snapshot_at, :retrieved_at, :description)
            ON CONFLICT (slug) DO UPDATE SET
                name = EXCLUDED.name, publisher = EXCLUDED.publisher,
                url = EXCLUDED.url, license = EXCLUDED.license,
                snapshot_at = EXCLUDED.snapshot_at,
                retrieved_at = EXCLUDED.retrieved_at,
                description = EXCLUDED.description
            RETURNING id
        """), vars(args)).scalar_one()

        connection.execute(text("""
            INSERT INTO public.road_segments
                (source_id, source_object_type, source_object_id, name, ref,
                 road_class, is_link, surface, lanes, maxspeed, oneway, access,
                 toll, bridge, tunnel, operator, network, status, geom)
            SELECT
                :source_id, 'way', way_id, name, ref,
                CASE WHEN right(highway, 5) = '_link'
                     THEN left(highway, length(highway) - 5) ELSE highway END,
                right(highway, 5) = '_link', surface, lanes, maxspeed, oneway,
                access, toll, bridge, tunnel, operator, network, 'active', geom
            FROM staging_osm_roads.road_lines
            WHERE true
            ON CONFLICT (source_id, source_object_type, source_object_id) DO UPDATE SET
                name = EXCLUDED.name, ref = EXCLUDED.ref,
                road_class = EXCLUDED.road_class, is_link = EXCLUDED.is_link,
                surface = EXCLUDED.surface, lanes = EXCLUDED.lanes,
                maxspeed = EXCLUDED.maxspeed, oneway = EXCLUDED.oneway,
                access = EXCLUDED.access, toll = EXCLUDED.toll,
                bridge = EXCLUDED.bridge, tunnel = EXCLUDED.tunnel,
                operator = EXCLUDED.operator, network = EXCLUDED.network,
                status = EXCLUDED.status, geom = EXCLUDED.geom
        """), {"source_id": source_id})
        connection.execute(text("""
            DELETE FROM public.road_segments AS r
            WHERE r.source_id = :source_id
              AND NOT EXISTS (
                  SELECT 1 FROM staging_osm_roads.road_lines AS s
                  WHERE s.way_id = r.source_object_id AND r.source_object_type = 'way'
              )
        """), {"source_id": source_id})
    engine.dispose()
    return count


def import_osm(input_path: Path) -> float:
    path = input_path.expanduser().resolve(strict=True)
    if not path.is_file() or not (path.name.endswith(".osm.pbf") or path.suffix == ".osm"):
        raise ValueError("--input must be an existing .osm.pbf or .osm file")
    engine = create_engine(database_url())
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS staging_osm_roads CASCADE"))
        connection.execute(text("CREATE SCHEMA staging_osm_roads"))
    engine.dispose()

    env = os.environ.copy()
    env["OSM_INPUT_DIR"] = str(path.parent)
    command = [
        "docker", "compose", "run", "--rm", "-T", "--no-deps", "osm2pgsql",
        "--create", "--slim", "--drop", "--output=flex",
        "--style=/config/roads.lua", "--schema=staging_osm_roads",
        "--middle-schema=staging_osm_roads",
        "--host=postgres", "--port=5432",
        f"--database={os.environ.get('POSTGRES_DB', 'russia_map')}",
        f"--username={os.environ.get('POSTGRES_USER', 'russia_map')}",
        f"/input/{path.name}",
    ]
    started = time.perf_counter()
    subprocess.run(command, cwd=REPO_ROOT, env=env, check=True)
    return time.perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("import", "normalize"):
        command = subparsers.add_parser(action)
        if action == "import":
            command.add_argument("--input", type=Path, required=True)
            command.add_argument("--timings-json", type=Path)
        command.add_argument("--source-slug", dest="slug", required=True)
        command.add_argument("--source-name", dest="name", required=True)
        command.add_argument("--source-url", dest="url", required=True)
        command.add_argument("--publisher", default="OpenStreetMap contributors")
        command.add_argument("--license", default="ODbL 1.0")
        command.add_argument("--snapshot-at", type=aware_datetime)
        command.add_argument("--retrieved-at", type=aware_datetime, required=True)
        command.add_argument("--description")
    args = parser.parse_args()
    import_seconds = None
    if args.action == "import":
        import_seconds = import_osm(args.input)
    started = time.perf_counter()
    count = normalize(args)
    normalize_seconds = time.perf_counter() - started
    if args.action == "import" and args.timings_json:
        args.timings_json.write_text(json.dumps({
            "osm2pgsql_import_seconds": import_seconds,
            "normalization_seconds": normalize_seconds,
        }, indent=2), encoding="utf-8")
    print(f"Normalized {count} major road ways for source {args.slug}")


if __name__ == "__main__":
    main()
