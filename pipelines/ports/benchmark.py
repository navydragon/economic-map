"""Measure an imported port source and sample its production Martin tiles."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx
from google.protobuf.message import DecodeError
import mapbox_vector_tile
from sqlalchemy import create_engine, text

from import_ports import database_url


ZOOMS = (5, 7, 9, 11, 13)
FACILITY_CLASSES = ("commercial_port", "cargo_terminal", "fishing_port", "port")
SOURCE_TYPES = ("node", "way", "relation")
MERCATOR_ORIGIN = 20037508.342789244
METADATA_FIELDS = ("named", "name_en", "water_context", "sea", "cargo", "operator",
                   "owner", "website", "wikidata", "wikipedia", "access")

# The projected_points CTE is provided by density_hotspot. Unit tests execute
# this exact bucket/rank query on synthetic projected points without PostGIS.
HOTSPOT_BUCKET_SQL = """
, buckets AS (
    SELECT CAST(LEAST(:max_tile, GREATEST(0,
        FLOOR((mercator_x + :origin) / :world_width * :world))) AS integer) AS x,
           CAST(LEAST(:max_tile, GREATEST(0,
        FLOOR((:origin - mercator_y) / :world_width * :world))) AS integer) AS y
    FROM projected_points
)
SELECT x, y, count(*) AS candidate_point_count
FROM buckets
GROUP BY x, y
ORDER BY candidate_point_count DESC, x ASC, y ASC
LIMIT 1
"""


def eligible_at_zoom(zoom: int, name: str | None) -> bool:
    """Mirror ports_mvt's named-only z5–z6 and all-port z7+ rule."""
    return zoom >= 7 or (zoom >= 5 and bool(name and name.strip()))


def density_hotspot(connection, source_id: int, zoom: int) -> dict | None:
    if zoom < 5:
        return None
    row = connection.execute(text("""
        WITH projected_points AS (
            SELECT ST_X(projected) AS mercator_x,
                   ST_Y(projected) AS mercator_y
            FROM (
                SELECT ST_Transform(ST_SetSRID(ST_MakePoint(
                    ST_X(geom),
                    LEAST(85.05112878, GREATEST(-85.05112878, ST_Y(geom)))
                ), 4326), 3857) AS projected
                FROM public.ports
                WHERE source_id = :source_id
                  AND (:include_unnamed OR NULLIF(btrim(name), '') IS NOT NULL)
            ) AS clamped
        )
    """ + HOTSPOT_BUCKET_SQL), {
        "source_id": source_id, "include_unnamed": zoom >= 7,
        "world": 2**zoom, "max_tile": 2**zoom - 1,
        "origin": MERCATOR_ORIGIN, "world_width": 2 * MERCATOR_ORIGIN,
    }).mappings().one_or_none()
    return dict(row) if row else None


def distribution(connection, source_id: int, column: str, values: tuple[str, ...],
                 total: int) -> dict[str, dict]:
    # Column names and allowed values are constants, never user input.
    rows = connection.execute(text(f"""
        SELECT {column} AS value, count(*) AS count
        FROM public.ports WHERE source_id = :source_id GROUP BY 1
    """), {"source_id": source_id}).all()
    counts = {row.value: row.count for row in rows}
    return {value: {"count": counts.get(value, 0),
                    "percent": round(100 * counts.get(value, 0) / total, 2)}
            for value in values}


def audit_samples(connection, source_id: int) -> dict:
    rows = connection.execute(text("""
        WITH ranked AS (
            SELECT id, source_object_type, source_object_id, name, facility_class,
                   water_context, cargo, operator,
                   ST_X(geom) AS longitude, ST_Y(geom) AS latitude,
                   row_number() OVER (PARTITION BY facility_class
                       ORDER BY source_object_type, source_object_id) AS rank
            FROM public.ports WHERE source_id = :source_id
        )
        SELECT id, source_object_type, source_object_id, name, facility_class,
               water_context, cargo, operator, longitude, latitude
        FROM ranked WHERE rank <= 10
        ORDER BY facility_class, source_object_type, source_object_id
    """), {"source_id": source_id}).mappings().all()
    by_class = {key: [] for key in FACILITY_CLASSES}
    for row in rows:
        by_class[row["facility_class"]].append(dict(row))
    unnamed = connection.execute(text("""
        SELECT source_object_type, source_object_id, facility_class,
               ST_X(geom) AS longitude, ST_Y(geom) AS latitude
        FROM public.ports WHERE source_id = :source_id
          AND NULLIF(btrim(name), '') IS NULL
        ORDER BY source_object_type, source_object_id LIMIT 10
    """), {"source_id": source_id}).mappings().all()
    return {"by_facility_class": by_class, "unnamed": [dict(row) for row in unnamed]}


def collect_database(source_slug: str) -> tuple[dict, dict, list[tuple[float, float]],
                                                dict[int, dict], set[int]]:
    engine = create_engine(database_url())
    try:
        with engine.connect() as connection:
            source = connection.execute(text("""
                SELECT id, slug, name, publisher, url, license, snapshot_at, retrieved_at
                FROM public.data_sources WHERE slug = :slug
            """), {"slug": source_slug}).mappings().one()
            source_id = source["id"]
            dataset = {
                "slug": source["slug"], "name": source["name"],
                "publisher": source["publisher"], "url": source["url"],
                "license": source["license"],
                "snapshot_at": source["snapshot_at"].isoformat() if source["snapshot_at"] else None,
                "retrieved_at": source["retrieved_at"].isoformat(),
                "input_filename": Path(urlsplit(source["url"]).path).name,
            }
            counts = connection.execute(text("""
                SELECT count(*) AS canonical_rows, ST_Extent(geom)::text AS extent,
                    count(*) FILTER (WHERE NULLIF(btrim(name), '') IS NOT NULL) AS named,
                    count(*) FILTER (WHERE NULLIF(btrim(name_en), '') IS NOT NULL) AS name_en,
                    count(*) FILTER (WHERE water_context IS NOT NULL) AS water_context,
                    count(*) FILTER (WHERE water_context = 'sea') AS sea,
                    count(*) FILTER (WHERE NULLIF(btrim(cargo), '') IS NOT NULL) AS cargo,
                    count(*) FILTER (WHERE NULLIF(btrim(operator), '') IS NOT NULL) AS operator,
                    count(*) FILTER (WHERE NULLIF(btrim(owner), '') IS NOT NULL) AS owner,
                    count(*) FILTER (WHERE NULLIF(btrim(website), '') IS NOT NULL) AS website,
                    count(*) FILTER (WHERE NULLIF(btrim(wikidata), '') IS NOT NULL) AS wikidata,
                    count(*) FILTER (WHERE NULLIF(btrim(wikipedia), '') IS NOT NULL) AS wikipedia,
                    count(*) FILTER (WHERE NULLIF(btrim(access), '') IS NOT NULL) AS access,
                    count(*) FILTER (WHERE geom IS NULL) AS null_geometry,
                    count(*) FILTER (WHERE geom IS NOT NULL AND ST_IsEmpty(geom)) AS empty_geometry,
                    count(*) FILTER (WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)) AS invalid_geometry,
                    count(*) FILTER (WHERE geom IS NOT NULL AND ST_GeometryType(geom) <> 'ST_Point') AS non_point_geometry,
                    count(*) FILTER (WHERE geom IS NOT NULL AND ST_SRID(geom) <> 4326) AS wrong_srid
                FROM public.ports WHERE source_id = :source_id
            """), {"source_id": source_id}).mappings().one()
            total = counts["canonical_rows"]
            if not total:
                raise ValueError(f"No canonical port rows for source {source_slug}")
            sizes = connection.execute(text("""
                SELECT pg_relation_size('public.ports'::regclass) AS table_bytes,
                       pg_relation_size('public.ports_geom_gix'::regclass) AS spatial_index_bytes,
                       pg_indexes_size('public.ports'::regclass) AS all_indexes_bytes,
                       pg_total_relation_size('public.ports'::regclass) AS total_relation_bytes
            """)).mappings().one()
            staging_exists = connection.scalar(text(
                "SELECT to_regclass('staging_osm_ports.port_features') IS NOT NULL"))
            staging_rows = connection.scalar(text(
                "SELECT count(*) FROM staging_osm_ports.port_features")) if staging_exists else None
            keys = connection.execute(text("""
                SELECT count(*) FROM (
                    SELECT source_id, source_object_type, source_object_id
                    FROM public.ports WHERE source_id = :source_id
                    GROUP BY 1, 2, 3 HAVING count(*) > 1
                ) AS duplicates
            """), {"source_id": source_id}).scalar_one()
            ids = connection.execute(text("""
                SELECT count(*) FROM (
                    SELECT id FROM public.ports WHERE source_id = :source_id
                    GROUP BY id HAVING count(*) > 1
                ) AS duplicates
            """), {"source_id": source_id}).scalar_one()
            locations = connection.execute(text("""
                WITH ranked AS (
                    SELECT ST_X(geom) AS lon, ST_Y(geom) AS lat,
                           row_number() OVER (ORDER BY ST_X(geom), ST_Y(geom),
                               source_object_type, source_object_id) AS rank,
                           count(*) OVER () AS total_rows
                    FROM public.ports WHERE source_id = :source_id
                )
                SELECT lon, lat FROM ranked
                WHERE rank IN (1, (total_rows + 1) / 2, total_rows)
                ORDER BY rank
            """), {"source_id": source_id}).all()
            hotspots = {zoom: hit for zoom in ZOOMS
                        if (hit := density_hotspot(connection, source_id, zoom)) is not None}
            canonical_ids = set(connection.scalars(text(
                "SELECT id FROM public.ports WHERE source_id = :source_id"),
                {"source_id": source_id}))
            database = {
                "staging_rows": staging_rows, "canonical_rows": total,
                "staging_matches_canonical": staging_rows == total if staging_rows is not None else None,
                "staging_comparison_note": (
                    "Staging is the current Flex candidate set; normalization upserts every staged object "
                    "and deletes absent objects for this source. Counts should match in this isolated run. "
                    "A mismatch requires investigating the staged keys, source scope, and normalization run."
                ),
                "extent": counts["extent"], "sizes_bytes": dict(sizes),
            }
            coverage = {field: {"count": counts[field],
                                "percent": round(100 * counts[field] / total, 2)}
                        for field in METADATA_FIELDS}
            quality = {key: counts[key] for key in (
                "null_geometry", "empty_geometry", "invalid_geometry",
                "non_point_geometry", "wrong_srid")}
            quality.update({"duplicate_source_key_groups": keys, "duplicate_canonical_id_groups": ids})
            measurements = {
                "database": database,
                "facility_classes": distribution(connection, source_id, "facility_class", FACILITY_CLASSES, total),
                "source_object_types": distribution(connection, source_id, "source_object_type", SOURCE_TYPES, total),
                "metadata_coverage": coverage,
                "quality": quality,
                "audit_samples": audit_samples(connection, source_id),
            }
        return dataset, measurements, [(row.lon, row.lat) for row in locations], hotspots, canonical_ids
    finally:
        engine.dispose()


def tile_coordinates(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    world = 2**zoom
    lat = max(min(lat, 85.05112878), -85.05112878)
    x = math.floor((lon + 180) / 360 * world)
    y = math.floor((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * world)
    return max(0, min(world - 1, x)), max(0, min(world - 1, y))


def sample_plan(locations: list[tuple[float, float]], hotspots: dict[int, dict]) -> list[dict]:
    plan = []
    for zoom in ZOOMS:
        tiles = sorted({tile_coordinates(lon, lat, zoom) for lon, lat in locations})
        by_tile = {(x, y): {"z": zoom, "x": x, "y": y,
                            "sample_kinds": ["representative"]} for x, y in tiles}
        if hotspot := hotspots.get(zoom):
            key = hotspot["x"], hotspot["y"]
            sample = by_tile.setdefault(key, {"z": zoom, "x": key[0], "y": key[1],
                                              "sample_kinds": []})
            sample["sample_kinds"].append("density_hotspot")
            sample["candidate_point_count"] = hotspot["candidate_point_count"]
        plan.extend(by_tile[key] for key in sorted(by_tile))
    return plan


def sample_tiles(martin_url: str, locations: list[tuple[float, float]],
                 hotspots: dict[int, dict], canonical_ids: set[int]) -> list[dict]:
    samples = []
    with httpx.Client(timeout=30, headers={
        "Accept": "application/x-protobuf", "Accept-Encoding": "gzip",
    }) as client:
        for planned in sample_plan(locations, hotspots):
            z, x, y = planned["z"], planned["x"], planned["y"]
            started = time.perf_counter()
            sample = {**planned, "http_status": None, "wire_bytes": None,
                      "decoded_payload_bytes": None, "feature_count": None,
                      "decode_error": None}
            try:
                response = client.get(f"{martin_url.rstrip('/')}/ports/{z}/{x}/{y}")
                sample.update({"http_status": response.status_code,
                               "wire_bytes": response.num_bytes_downloaded,
                               "decoded_payload_bytes": len(response.content),
                               "content_encoding": response.headers.get("content-encoding"),
                               "feature_count": 0})
                if response.status_code == 200 and response.content:
                    try:
                        decoded = mapbox_vector_tile.decode(response.content)
                        if "ports" not in decoded:
                            raise ValueError("MVT source layer 'ports' missing")
                        features = decoded["ports"]["features"]
                        sample["feature_count"] = len(features)
                        for feature in features:
                            if feature.get("id") not in canonical_ids:
                                raise ValueError(f"Noncanonical port feature ID: {feature.get('id')}")
                            if feature.get("geometry", {}).get("type") != "Point":
                                raise ValueError("Port MVT geometry is not Point")
                            if z == 5 and not feature.get("properties", {}).get("name", "").strip():
                                raise ValueError("Unnamed port returned at z5")
                    except (DecodeError, ValueError, KeyError, TypeError) as error:
                        sample["decode_error"] = str(error)
            except httpx.RequestError as error:
                sample["error"] = str(error)
            sample["request_seconds"] = round(time.perf_counter() - started, 3)
            samples.append(sample)
    return samples


def file_facts(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"pbf_bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def markdown(report: dict) -> str:
    dataset, db = report["dataset"], report["database"]
    lines = [
        "# Port benchmark", "", "## Dataset", "",
        f"- URL: {dataset['url']}", f"- Filename: {dataset['input_filename']}",
        f"- Source slug: {dataset['slug']}", f"- Source name: {dataset['name']}",
        f"- Snapshot supplied: {dataset['snapshot_at'] or 'unknown'}",
        f"- Retrieved: {dataset['retrieved_at']}",
        f"- PBF size: {dataset.get('pbf_bytes', 'not supplied')} bytes",
        f"- SHA-256: {dataset.get('sha256', 'not supplied')}",
        "", "## Timing", "", "| Stage | Seconds |", "|---|---:|",
    ]
    for stage, seconds in report["timing_seconds"].items():
        lines.append(f"| {stage} | {seconds:.3f} |" if seconds is not None else
                     f"| {stage} | not measured |")
    lines += [
        "", "## Database", "",
        f"- Staging rows: {db['staging_rows']}",
        f"- Canonical rows: {db['canonical_rows']}",
        f"- Staging equals canonical: {db['staging_matches_canonical']}",
        f"- Comparison: {db['staging_comparison_note']}",
        f"- Extent (SRID 4326): {db['extent']}",
        "", "| Relation size | Bytes |", "|---|---:|",
    ]
    for name, size in db["sizes_bytes"].items():
        lines.append(f"| {name} | {size:,} |")
    for heading, key in (("Facility classes", "facility_classes"),
                         ("Source object types", "source_object_types"),
                         ("Metadata coverage", "metadata_coverage")):
        lines += ["", f"## {heading}", "", "| Category | Count | Percent |", "|---|---:|---:|"]
        for name, entry in report[key].items():
            lines.append(f"| {name} | {entry['count']} | {entry['percent']:.2f}% |")
    lines += ["", "## Geometry and identity quality", "", "| Check | Count |", "|---|---:|"]
    for name, count in report["quality"].items():
        lines.append(f"| {name} | {count} |")
    lines += ["", "## Deterministic semantic audit samples", "",
              "These samples support human sanity checks; they do not establish complete coverage."]
    for facility_class, rows in report["audit_samples"]["by_facility_class"].items():
        lines += ["", f"### {facility_class}", "",
                  "| Canonical ID | OSM type | OSM ID | Name | Class | Water | Cargo | Operator | Longitude | Latitude |",
                  "|---:|---|---:|---|---|---|---|---|---:|---:|"]
        for row in rows:
            values = (row[key] for key in ("id", "source_object_type", "source_object_id", "name",
                                           "facility_class", "water_context", "cargo", "operator",
                                           "longitude", "latitude"))
            lines.append("| " + " | ".join(str(value if value is not None else "")
                                           .replace("|", "/").replace("\n", " ") for value in values) + " |")
    lines += ["", "### Unnamed examples", "",
              "| OSM type | OSM ID | Class | Longitude | Latitude |",
              "|---|---:|---|---:|---:|"]
    for row in report["audit_samples"]["unnamed"]:
        lines.append("| " + " | ".join(str(row[key]) for key in (
            "source_object_type", "source_object_id", "facility_class", "longitude", "latitude")) + " |")
    lines += [
        "", "## Martin tile samples", "",
        "| z/x/y | Sample kinds | Candidate points | HTTP | Wire bytes | Decoded payload bytes | Features | Seconds | Decode error | Error |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for tile in report["tile_samples"]:
        lines.append(
            f"| {tile['z']}/{tile['x']}/{tile['y']} | "
            f"{', '.join(kind.replace('_', ' ') for kind in tile['sample_kinds'])} | "
            f"{tile.get('candidate_point_count', '—')} | {tile['http_status']} | "
            f"{tile['wire_bytes']} | {tile['decoded_payload_bytes']} | "
            f"{tile['feature_count']} | {tile['request_seconds']} | "
            f"{(tile.get('decode_error') or '').replace('|', '/')} | "
            f"{tile.get('error', '').replace('|', '/')} |"
        )
    lines += [
        "", "## Limits", "",
        "- The hotspot is one dense eligible point bucket per zoom, not an exhaustive worst-case latency search.",
        "- Candidate point counts can differ from decoded feature counts because MVT includes a 64/4096 buffer.",
        "- Individual request times are diagnostic and are not production latency SLOs.",
        "- Relation sizes cover the full table; source counts and quality cover the selected slug.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-slug", required=True)
    parser.add_argument("--martin-url", default="http://127.0.0.1:3000")
    parser.add_argument("--input-path", type=Path)
    parser.add_argument("--timings-json", type=Path)
    parser.add_argument("--download-seconds", type=float)
    parser.add_argument("--postgis-seconds", type=float)
    parser.add_argument("--migration-seconds", type=float)
    parser.add_argument("--martin-seconds", type=float)
    parser.add_argument("--json-out", type=Path, default=Path("benchmark.json"))
    parser.add_argument("--markdown-out", type=Path, default=Path("benchmark.md"))
    args = parser.parse_args()

    dataset, measurements, locations, hotspots, canonical_ids = collect_database(args.source_slug)
    if args.input_path:
        dataset.update(file_facts(args.input_path))
    import_timings = json.loads(args.timings_json.read_text(encoding="utf-8")) if args.timings_json else {}
    report = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "dataset": dataset,
        "timing_seconds": {
            "download_seconds": args.download_seconds,
            "postgis_start_seconds": args.postgis_seconds,
            "alembic_seconds": args.migration_seconds,
            "osm2pgsql_import_seconds": import_timings.get("osm2pgsql_import_seconds"),
            "normalization_seconds": import_timings.get("normalization_seconds"),
            "martin_start_seconds": args.martin_seconds,
        },
        **measurements,
        "tile_samples": sample_tiles(args.martin_url, locations, hotspots, canonical_ids),
    }
    args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_out.write_text(markdown(report), encoding="utf-8")
    if any(report["quality"].values()):
        raise SystemExit("Canonical port geometry or identity quality check failed; see report")
    if report["database"]["staging_matches_canonical"] is False:
        raise SystemExit("Staging and canonical counts differ; see report")
    if any(sample["http_status"] not in (200, 204) or sample.get("error")
           or sample.get("decode_error") for sample in report["tile_samples"]):
        raise SystemExit("Martin tile contract failed; see report")
    print(f"Wrote {args.json_out} and {args.markdown_out}")


if __name__ == "__main__":
    main()
