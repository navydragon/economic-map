"""Import an explicit local OSM extract, then normalize civilian port facilities."""

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
                count(*) FILTER (WHERE osm_type NOT IN ('N', 'W', 'R')
                    OR osm_id IS NULL
                    OR facility_class NOT IN
                        ('commercial_port', 'cargo_terminal', 'fishing_port', 'port')
                    OR facility_class IS NULL
                    OR water_context IS NOT NULL AND water_context NOT IN ('sea', 'river', 'lake')
                    OR geom IS NULL OR ST_IsEmpty(geom) OR NOT ST_IsValid(geom)
                    OR ST_SRID(geom) <> 4326
                    OR ST_GeometryType(geom) NOT IN
                        ('ST_Point', 'ST_Polygon', 'ST_MultiPolygon')),
                count(*) - count(DISTINCT (osm_type, osm_id))
            FROM staging_osm_ports.port_features
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
            INSERT INTO public.ports
                (source_id, source_object_type, source_object_id, name, name_en,
                 facility_class, water_context, cargo, operator, owner, website,
                 wikidata, wikipedia, access, status, geom)
            SELECT :source_id,
                CASE osm_type WHEN 'N' THEN 'node' WHEN 'W' THEN 'way' ELSE 'relation' END,
                osm_id, name, name_en, facility_class, water_context, cargo,
                operator, owner, website, wikidata, wikipedia, access, 'active',
                CASE WHEN ST_GeometryType(geom) = 'ST_Point' THEN geom
                     ELSE ST_PointOnSurface(geom) END
            FROM staging_osm_ports.port_features
            WHERE true
            ON CONFLICT (source_id, source_object_type, source_object_id) DO UPDATE SET
                name = EXCLUDED.name, name_en = EXCLUDED.name_en,
                facility_class = EXCLUDED.facility_class,
                water_context = EXCLUDED.water_context, cargo = EXCLUDED.cargo,
                operator = EXCLUDED.operator, owner = EXCLUDED.owner,
                website = EXCLUDED.website, wikidata = EXCLUDED.wikidata,
                wikipedia = EXCLUDED.wikipedia, access = EXCLUDED.access,
                status = EXCLUDED.status, geom = EXCLUDED.geom
        """), {"source_id": source_id})
        connection.execute(text("""
            DELETE FROM public.ports AS p
            WHERE p.source_id = :source_id
              AND NOT EXISTS (
                  SELECT 1 FROM staging_osm_ports.port_features AS s
                  WHERE s.osm_id = p.source_object_id
                    AND s.osm_type = CASE p.source_object_type
                        WHEN 'node' THEN 'N' WHEN 'way' THEN 'W' ELSE 'R' END
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
        connection.execute(text("DROP SCHEMA IF EXISTS staging_osm_ports CASCADE"))
        connection.execute(text("CREATE SCHEMA staging_osm_ports"))
    engine.dispose()

    env = os.environ.copy()
    env["OSM_INPUT_DIR"] = str(path.parent)
    command = [
        "docker", "compose", "run", "--rm", "-T", "--no-deps", "osm2pgsql",
        "--create", "--slim", "--drop", "--output=flex",
        "--style=/config/ports.lua", "--schema=staging_osm_ports",
        "--middle-schema=staging_osm_ports",
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
    print(f"Normalized {count} civilian port facilities for source {args.slug}")


if __name__ == "__main__":
    main()
