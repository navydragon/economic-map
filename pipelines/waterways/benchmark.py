"""Measure an imported waterway source and sample production Martin tiles."""

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

from import_waterways import database_url


ZOOMS = (5, 7, 9, 11, 13)
WATERWAY_CLASSES = ("river", "canal", "fairway")
NAVIGATION_FIELDS = ("boat_access", "motorboat_access", "ship_access",
                     "oneway_boat", "cemt_class")
METADATA_FIELDS = (*NAVIGATION_FIELDS, "usage", "service", "width",
                   "intermittent", "tidal", "operator", "wikidata", "wikipedia")
TOP_VALUE_FIELDS = ("cemt_class", "boat_access", "motorboat_access",
                    "ship_access", "oneway_boat", "usage")
PUBLIC_FIELDS = {"name", "ref", "waterway_class", "boat_access", "motorboat_access",
                 "ship_access", "oneway_boat", "cemt_class", "usage", "intermittent", "tidal"}
MERCATOR_ORIGIN = 20037508.342789244
EXPLICIT_NAVIGATION_SQL = " OR ".join(
    f"NULLIF(btrim({field}), '') IS NOT NULL" for field in NAVIGATION_FIELDS)

# The projected_midpoints CTE comes from density_hotspot. Unit tests run this
# exact ranking SQL on synthetic projected points without PostGIS or a PBF.
HOTSPOT_BUCKET_SQL = """
, buckets AS (
    SELECT CAST(LEAST(:max_tile, GREATEST(0,
        FLOOR((mercator_x + :origin) / :world_width * :world))) AS integer) AS x,
           CAST(LEAST(:max_tile, GREATEST(0,
        FLOOR((:origin - mercator_y) / :world_width * :world))) AS integer) AS y
    FROM projected_midpoints
)
SELECT x, y, count(*) AS candidate_midpoint_count
FROM buckets
GROUP BY x, y
ORDER BY candidate_midpoint_count DESC, x ASC, y ASC
LIMIT 1
"""


def tile_coordinates(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    world = 2**zoom
    lat = max(min(lat, 85.05112878), -85.05112878)
    x = math.floor((lon + 180) / 360 * world)
    y = math.floor((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * world)
    return max(0, min(world - 1, x)), max(0, min(world - 1, y))


def density_hotspot(connection, source_id: int, zoom: int) -> dict | None:
    if zoom < 5:
        return None
    row = connection.execute(text("""
        WITH midpoints AS (
            SELECT ST_LineInterpolatePoint(geom, 0.5) AS point
            FROM public.waterway_segments WHERE source_id = :source_id
        ), projected_midpoints AS (
            SELECT ST_X(projected) AS mercator_x,
                   ST_Y(projected) AS mercator_y
            FROM (
                SELECT ST_Transform(ST_SetSRID(ST_MakePoint(
                    ST_X(point),
                    LEAST(85.05112878, GREATEST(-85.05112878, ST_Y(point)))
                ), 4326), 3857) AS projected
                FROM midpoints
            ) AS clamped
        )
    """ + HOTSPOT_BUCKET_SQL), {
        "source_id": source_id, "world": 2**zoom, "max_tile": 2**zoom - 1,
        "origin": MERCATOR_ORIGIN, "world_width": 2 * MERCATOR_ORIGIN,
    }).mappings().one_or_none()
    return dict(row) if row else None


def ratio(count: int, total: int) -> dict:
    return {"count": count, "percentage": round(100 * count / total, 2)}


def navigation_counts(rows: list[dict]) -> tuple[dict, dict]:
    """Count synthetic or query-returned metadata without inferring navigability."""
    total = len(rows)
    coverage = {field: ratio(sum(row.get(field) is not None and
                                 (not isinstance(row[field], str) or bool(row[field].strip()))
                                 for row in rows), total)
                for field in METADATA_FIELDS}
    any_count = sum(any(row.get(field) is not None and
                        (not isinstance(row[field], str) or bool(row[field].strip()))
                        for field in NAVIGATION_FIELDS) for row in rows)
    coverage["explicit_navigation_any"] = ratio(any_count, total)
    matrix = {}
    for waterway_class in WATERWAY_CLASSES:
        class_rows = [row for row in rows if row["waterway_class"] == waterway_class]
        matrix[waterway_class] = {
            "explicit_navigation_any": sum(any(row.get(field) is not None and
                (not isinstance(row[field], str) or bool(row[field].strip()))
                for field in NAVIGATION_FIELDS) for row in class_rows),
            **{field: sum(row.get(field) is not None and
                           (not isinstance(row[field], str) or bool(row[field].strip()))
                          for row in class_rows)
               for field in ("cemt_class", "ship_access", "motorboat_access", "boat_access")},
        }
    return coverage, matrix


def top_values(values: list[str | None], limit: int = 20) -> list[dict]:
    counts: dict[str, int] = {}
    for value in values:
        if value is not None and value.strip():
            counts[value] = counts.get(value, 0) + 1
    return [{"value": value, "count": count} for value, count in
            sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def value_distributions(connection, source_id: int) -> dict:
    distributions = {}
    for field in TOP_VALUE_FIELDS:
        # Field names are constants from this file, not CLI input.
        rows = connection.execute(text(f"""
            SELECT {field} AS value, count(*) AS count
            FROM public.waterway_segments
            WHERE source_id = :source_id AND NULLIF(btrim({field}), '') IS NOT NULL
            GROUP BY {field} ORDER BY count DESC, value ASC LIMIT 20
        """), {"source_id": source_id}).all()
        distributions[field] = [{"value": row.value, "count": row.count} for row in rows]
    return distributions


AUDIT_COLUMNS = """
    id, source_object_id, name, ref, waterway_class, boat_access,
    motorboat_access, ship_access, oneway_boat, cemt_class, usage,
    service, width, intermittent, tidal, operator
"""


def audit_samples(connection, source_id: int) -> dict:
    by_class = {key: [] for key in WATERWAY_CLASSES}
    rows = connection.execute(text(f"""
        WITH ranked AS (
            SELECT {AUDIT_COLUMNS},
                   row_number() OVER (PARTITION BY waterway_class
                       ORDER BY source_object_id) AS rank
            FROM public.waterway_segments WHERE source_id = :source_id
        )
        SELECT {AUDIT_COLUMNS} FROM ranked WHERE rank <= 10
        ORDER BY waterway_class, source_object_id
    """), {"source_id": source_id}).mappings().all()
    for row in rows:
        by_class[row["waterway_class"]].append(dict(row))
    explicit = connection.execute(text(f"""
        SELECT {AUDIT_COLUMNS} FROM public.waterway_segments
        WHERE source_id = :source_id AND ({EXPLICIT_NAVIGATION_SQL})
        ORDER BY waterway_class ASC, source_object_id ASC LIMIT 20
    """), {"source_id": source_id}).mappings().all()
    return {"by_class": by_class, "explicit_navigation": [dict(row) for row in explicit]}


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
            counts = connection.execute(text(f"""
                SELECT count(*) AS canonical_rows, ST_Extent(geom)::text AS extent,
                    count(*) FILTER (WHERE NULLIF(btrim(name), '') IS NOT NULL) AS named,
                    count(*) FILTER (WHERE NULLIF(btrim(name_en), '') IS NOT NULL) AS name_en,
                    count(*) FILTER (WHERE NULLIF(btrim(ref), '') IS NOT NULL) AS ref,
                    {', '.join(
                        f"count(*) FILTER (WHERE {field} IS NOT NULL) AS {field}"
                        if field in ('intermittent', 'tidal') else
                        f"count(*) FILTER (WHERE NULLIF(btrim({field}), '') IS NOT NULL) AS {field}"
                        for field in METADATA_FIELDS)},
                    count(*) FILTER (WHERE {EXPLICIT_NAVIGATION_SQL}) AS explicit_navigation_any,
                    count(*) FILTER (WHERE geom IS NULL) AS null_geometry,
                    count(*) FILTER (WHERE geom IS NOT NULL AND ST_IsEmpty(geom)) AS empty_geometry,
                    count(*) FILTER (WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)) AS invalid_geometry,
                    count(*) FILTER (WHERE geom IS NOT NULL AND ST_SRID(geom) <> 4326) AS wrong_srid,
                    count(*) FILTER (WHERE geom IS NOT NULL AND ST_GeometryType(geom) <> 'ST_LineString') AS non_linestring_geometry,
                    count(*) FILTER (WHERE geom IS NOT NULL AND ST_NPoints(geom) < 2) AS fewer_than_two_points,
                    sum(ST_NPoints(geom)) AS total_vertices,
                    avg(ST_NPoints(geom)) AS average_vertices_per_segment,
                    max(ST_NPoints(geom)) AS maximum_vertices_per_segment,
                    avg(ST_Length(geom::geography)) AS average_length_m,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY ST_Length(geom::geography)) AS median_length_m,
                    percentile_cont(0.95) WITHIN GROUP (ORDER BY ST_Length(geom::geography)) AS p95_length_m,
                    max(ST_Length(geom::geography)) AS maximum_length_m
                FROM public.waterway_segments WHERE source_id = :source_id
            """), {"source_id": source_id}).mappings().one()
            total = counts["canonical_rows"]
            if not total:
                raise ValueError(f"No canonical waterway rows for source {source_slug}")
            sizes = connection.execute(text("""
                SELECT pg_relation_size('public.waterway_segments'::regclass) AS table_bytes,
                       pg_relation_size('public.waterway_segments_geom_gix'::regclass) AS spatial_index_bytes,
                       pg_indexes_size('public.waterway_segments'::regclass) AS all_indexes_bytes,
                       pg_total_relation_size('public.waterway_segments'::regclass) AS total_relation_bytes
            """)).mappings().one()
            staging_exists = connection.scalar(text(
                "SELECT to_regclass('staging_osm_waterways.waterway_lines') IS NOT NULL"))
            staging_rows = connection.scalar(text(
                "SELECT count(*) FROM staging_osm_waterways.waterway_lines")) if staging_exists else None
            class_rows = connection.execute(text("""
                SELECT waterway_class, count(*) AS count
                FROM public.waterway_segments WHERE source_id = :source_id
                GROUP BY waterway_class
            """), {"source_id": source_id}).all()
            class_counts = {row.waterway_class: row.count for row in class_rows}
            classes = {key: ratio(class_counts.get(key, 0), total) for key in WATERWAY_CLASSES}
            matrix_rows = connection.execute(text(f"""
                SELECT waterway_class,
                    count(*) FILTER (WHERE {EXPLICIT_NAVIGATION_SQL}) AS explicit_navigation_any,
                    {', '.join(f"count(*) FILTER (WHERE NULLIF(btrim({field}), '') IS NOT NULL) AS {field}"
                               for field in ('cemt_class', 'ship_access', 'motorboat_access', 'boat_access'))}
                FROM public.waterway_segments WHERE source_id = :source_id
                GROUP BY waterway_class
            """), {"source_id": source_id}).mappings().all()
            matrix = {key: {field: 0 for field in (
                "explicit_navigation_any", "cemt_class", "ship_access", "motorboat_access", "boat_access")}
                for key in WATERWAY_CLASSES}
            for row in matrix_rows:
                matrix[row["waterway_class"]] = {key: row[key] for key in matrix[row["waterway_class"]]}
            duplicate_keys = connection.scalar(text("""
                SELECT count(*) FROM (
                    SELECT source_id, source_object_type, source_object_id
                    FROM public.waterway_segments WHERE source_id = :source_id
                    GROUP BY 1, 2, 3 HAVING count(*) > 1
                ) AS duplicates
            """), {"source_id": source_id})
            duplicate_ids = connection.scalar(text("""
                SELECT count(*) FROM (
                    SELECT id FROM public.waterway_segments WHERE source_id = :source_id
                    GROUP BY id HAVING count(*) > 1
                ) AS duplicates
            """), {"source_id": source_id})
            representatives = connection.execute(text("""
                WITH midpoints AS (
                    SELECT source_object_id, ST_LineInterpolatePoint(geom, 0.5) AS point
                    FROM public.waterway_segments WHERE source_id = :source_id
                ), ranked AS (
                    SELECT point, row_number() OVER (
                        ORDER BY ST_X(point), ST_Y(point), source_object_id) AS rank,
                        count(*) OVER () AS total_rows
                    FROM midpoints
                )
                SELECT ST_X(point) AS lon, ST_Y(point) AS lat FROM ranked
                WHERE rank IN (1, (total_rows + 1) / 2, total_rows)
                ORDER BY rank
            """), {"source_id": source_id}).all()
            hotspots = {zoom: hit for zoom in ZOOMS
                        if (hit := density_hotspot(connection, source_id, zoom)) is not None}
            if len(hotspots) != len(ZOOMS):
                raise ValueError("No waterway midpoint hotspot at every benchmark zoom")
            ids = set(connection.scalars(text("""
                SELECT id FROM public.waterway_segments WHERE source_id = :source_id
            """), {"source_id": source_id}))
            measurements = {
                "database": {
                    "staging_rows": staging_rows, "canonical_rows": total,
                    "staging_matches_canonical": staging_rows == total if staging_rows is not None else None,
                    "staging_comparison_note": (
                        "The Flex staging table has one row per accepted OSM way. Normalization "
                        "upserts every staged way and removes missing ways for this source slug; "
                        "counts should match in this isolated source run."
                    ),
                    "extent": counts["extent"], "sizes_bytes": dict(sizes),
                },
                "waterway_classes": classes,
                "naming_coverage": {
                    "named": ratio(counts["named"], total),
                    "unnamed": ratio(total - counts["named"], total),
                    "name_en": ratio(counts["name_en"], total),
                    "ref": ratio(counts["ref"], total),
                },
                "navigation_coverage": {
                    **{field: ratio(counts[field], total) for field in METADATA_FIELDS},
                    "explicit_navigation_any": ratio(counts["explicit_navigation_any"], total),
                },
                "explicit_navigation_any_count": counts["explicit_navigation_any"],
                "explicit_navigation_any_percentage": round(
                    100 * counts["explicit_navigation_any"] / total, 2),
                "navigation_matrix": matrix,
                "value_distributions": value_distributions(connection, source_id),
                "geometry_quality": {
                    **{key: counts[key] for key in (
                        "null_geometry", "empty_geometry", "invalid_geometry", "wrong_srid",
                        "non_linestring_geometry", "fewer_than_two_points")},
                    "duplicate_source_identity": duplicate_keys,
                    "duplicate_canonical_id": duplicate_ids,
                },
                "segment_complexity": {
                    "length_unit": "metres (PostGIS geography)",
                    "total_vertices": int(counts["total_vertices"]),
                    "average_vertices_per_segment": round(float(counts["average_vertices_per_segment"]), 2),
                    "maximum_vertices_per_segment": counts["maximum_vertices_per_segment"],
                    **{key: round(float(counts[key]), 2) for key in (
                        "average_length_m", "median_length_m", "p95_length_m", "maximum_length_m")},
                },
                "audit_samples": audit_samples(connection, source_id),
            }
        return dataset, measurements, [(r.lon, r.lat) for r in representatives], hotspots, ids
    finally:
        engine.dispose()


def sample_plan(locations: list[tuple[float, float]], hotspots: dict[int, dict]) -> list[dict]:
    plan = []
    for zoom in ZOOMS:
        coordinates = sorted({tile_coordinates(lon, lat, zoom) for lon, lat in locations})
        by_tile = {(x, y): {"z": zoom, "x": x, "y": y,
                            "sample_kinds": ["representative"]} for x, y in coordinates}
        hotspot = hotspots.get(zoom)
        if hotspot:
            key = hotspot["x"], hotspot["y"]
            sample = by_tile.setdefault(key, {"z": zoom, "x": key[0], "y": key[1],
                                              "sample_kinds": []})
            sample["sample_kinds"].append("density_hotspot")
            sample["candidate_midpoint_count"] = hotspot["candidate_midpoint_count"]
        plan.extend(by_tile[key] for key in sorted(by_tile))
    return plan


def sample_tiles(martin_url: str, locations: list[tuple[float, float]],
                 hotspots: dict[int, dict], canonical_ids: set[int]) -> list[dict]:
    samples = []
    with httpx.Client(timeout=60, headers={
        "Accept": "application/x-protobuf", "Accept-Encoding": "gzip",
    }) as client:
        for planned in sample_plan(locations, hotspots):
            zoom, x, y = planned["z"], planned["x"], planned["y"]
            sample = {**planned, "http_status": None, "wire_bytes": None,
                      "decoded_payload_bytes": None, "feature_count": None,
                      "decode_error": None}
            started = time.perf_counter()
            try:
                response = client.get(f"{martin_url.rstrip('/')}/waterway_segments/{zoom}/{x}/{y}")
                sample.update({"http_status": response.status_code,
                               "wire_bytes": response.num_bytes_downloaded,
                               "decoded_payload_bytes": len(response.content),
                               "content_encoding": response.headers.get("content-encoding"),
                               "feature_count": 0})
                if response.status_code == 200 and response.content:
                    try:
                        decoded = mapbox_vector_tile.decode(response.content)
                        if set(decoded) != {"waterway_segments"}:
                            raise ValueError("MVT source layer 'waterway_segments' missing or unexpected layer")
                        features = decoded["waterway_segments"]["features"]
                        sample["feature_count"] = len(features)
                        for feature in features:
                            if (not isinstance(feature.get("id"), int)
                                    or isinstance(feature.get("id"), bool)
                                    or feature["id"] not in canonical_ids):
                                raise ValueError(f"Noncanonical waterway feature ID: {feature.get('id')}")
                            if feature.get("geometry", {}).get("type") not in ("LineString", "MultiLineString"):
                                raise ValueError("Waterway MVT geometry is not linear")
                            properties = feature.get("properties", {})
                            if not set(properties) <= PUBLIC_FIELDS:
                                raise ValueError("Unexpected waterway MVT property")
                            if properties.get("waterway_class") not in WATERWAY_CLASSES:
                                raise ValueError("Invalid waterway MVT class")
                            for field, value in properties.items():
                                expected = bool if field in ("intermittent", "tidal") else str
                                if not isinstance(value, expected):
                                    raise ValueError(f"Invalid waterway MVT property type: {field}")
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


def markdown_table(lines: list[str], title: str, values: dict[str, dict]) -> None:
    lines += ["", f"## {title}", "", "| Field | Count | Percentage |", "|---|---:|---:|"]
    for field, result in values.items():
        lines.append(f"| {field} | {result['count']} | {result['percentage']:.2f}% |")


def audit_table(lines: list[str], title: str, rows: list[dict]) -> None:
    columns = ("id", "source_object_id", "name", "ref", "waterway_class", "boat_access",
               "motorboat_access", "ship_access", "oneway_boat", "cemt_class", "usage",
               "service", "width", "intermittent", "tidal", "operator")
    lines += ["", f"### {title}", "", "| " + " | ".join(columns) + " |",
              "|" + "---|" * len(columns)]
    for row in rows:
        lines.append("| " + " | ".join(
            str(row.get(key) if row.get(key) is not None else "").replace("|", "/").replace("\n", " ")
            for key in columns) + " |")


def markdown(report: dict) -> str:
    dataset, db = report["dataset"], report["database"]
    lines = [
        "# Waterway benchmark", "", "## Dataset", "",
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
    for title, key in (("Waterway classes", "waterway_classes"),
                       ("Naming coverage", "naming_coverage"),
                       ("Explicit navigation and other metadata coverage", "navigation_coverage")):
        markdown_table(lines, title, report[key])
    lines += ["", "## Class × navigation matrix", "",
              "| Class | Explicit navigation any | CEMT | Ship | Motorboat | Boat |",
              "|---|---:|---:|---:|---:|---:|"]
    for waterway_class, counts in report["navigation_matrix"].items():
        lines.append(f"| {waterway_class} | {counts['explicit_navigation_any']} | "
                     f"{counts['cemt_class']} | {counts['ship_access']} | "
                     f"{counts['motorboat_access']} | {counts['boat_access']} |")
    lines += ["", "## Top source values", ""]
    for field, entries in report["value_distributions"].items():
        lines += [f"### {field}", "", "| Value | Count |", "|---|---:|"]
        for entry in entries:
            lines.append(f"| {entry['value'].replace('|', '/').replace(chr(10), ' ')} | {entry['count']} |")
        lines.append("")
    lines += ["## Geometry and identity quality", "", "| Check | Count |", "|---|---:|"]
    for name, count in report["geometry_quality"].items():
        lines.append(f"| {name} | {count} |")
    lines += ["", "## Segment complexity", "", "| Metric | Value |", "|---|---:|"]
    for name, value in report["segment_complexity"].items():
        lines.append(f"| {name} | {value} |")
    lines += ["", "## Deterministic semantic audit samples", "",
              "Samples support human review; they do not prove completeness or navigability."]
    for waterway_class, rows in report["audit_samples"]["by_class"].items():
        audit_table(lines, waterway_class, rows)
    audit_table(lines, "Segments with explicit navigation metadata",
                report["audit_samples"]["explicit_navigation"])
    lines += [
        "", "## Martin tile samples", "",
        "| z/x/y | Sample kinds | Candidate midpoints | HTTP | Wire bytes | Decoded bytes | Features | Seconds | Decode error | Error |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for tile in report["tile_samples"]:
        lines.append(
            f"| {tile['z']}/{tile['x']}/{tile['y']} | "
            f"{', '.join(kind.replace('_', ' ') for kind in tile['sample_kinds'])} | "
            f"{tile.get('candidate_midpoint_count', '—')} | {tile['http_status']} | "
            f"{tile['wire_bytes']} | {tile['decoded_payload_bytes']} | "
            f"{tile['feature_count']} | {tile['request_seconds']} | "
            f"{(tile.get('decode_error') or '').replace('|', '/')} | "
            f"{tile.get('error', '').replace('|', '/')} |"
        )
    lines += ["", "## Density-hotspot zoom summary", "",
              "| Zoom | Candidate midpoints | Actual MVT features | Wire bytes | Decoded bytes | Seconds |",
              "|---|---:|---:|---:|---:|---:|"]
    for zoom in ZOOMS:
        tile = next(t for t in report["tile_samples"] if t["z"] == zoom
                    and "density_hotspot" in t["sample_kinds"])
        lines.append(f"| z{zoom} | {tile['candidate_midpoint_count']} | "
                     f"{tile['feature_count']} | {tile['wire_bytes']} | "
                     f"{tile['decoded_payload_bytes']} | {tile['request_seconds']} |")
    lines += [
        "", "## Interpretation limits", "",
        "- River or canal classification does not imply navigability. Explicit navigation coverage measures OSM tagging, not the true navigable network.",
        "- Midpoint density is a fragmentation proxy, not the exact densest tile or an exhaustive worst case. Long segments can cross tiles whose midpoint lies elsewhere; the MVT query also has a buffer.",
        "- Actual decoded MVT feature counts are authoritative for requested tiles.",
        "- Workflow timings and single-request times are diagnostic, not production SLOs.",
        "- No production optimization is selected by this benchmark implementation.",
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
    if any(report["geometry_quality"].values()):
        raise SystemExit("Canonical waterway geometry or identity quality check failed; see report")
    if report["database"]["staging_matches_canonical"] is False:
        raise SystemExit("Staging and canonical counts differ; see report")
    if any(sample["http_status"] not in (200, 204) or sample.get("error")
           or sample.get("decode_error") for sample in report["tile_samples"]):
        raise SystemExit("Martin waterway tile contract failed; see report")
    print(f"Wrote {args.json_out} and {args.markdown_out}")


if __name__ == "__main__":
    main()
