"""Measure an already imported road source and sample its Martin vector tiles."""

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

from import_roads import database_url


ZOOMS = (5, 7, 9, 11, 13)


def distribution(connection, source_id: int, column: str) -> dict[str, int]:
    # Column names come only from this file, never from CLI input.
    rows = connection.execute(text(f"""
        SELECT COALESCE(NULLIF({column}, ''), '<unknown>') AS value, count(*) AS count
        FROM public.road_segments WHERE source_id = :source_id
        GROUP BY 1 ORDER BY count DESC, value
    """), {"source_id": source_id}).all()
    return {row.value: row.count for row in rows}


def collect_database(source_slug: str) -> tuple[dict, dict, list[tuple[float, float]]]:
    engine = create_engine(database_url())
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
            "input_filename": Path(urlsplit(source["url"]).path).name or None,
        }
        counts = connection.execute(text("""
            SELECT count(*) AS canonical_rows, ST_Extent(geom)::text AS extent,
                count(*) FILTER (WHERE NULLIF(btrim(name), '') IS NOT NULL) AS named,
                count(*) FILTER (WHERE is_link) AS link_rows,
                count(*) FILTER (WHERE NULLIF(btrim(surface), '') IS NOT NULL) AS surface_known,
                count(*) FILTER (WHERE NULLIF(btrim(lanes), '') IS NOT NULL) AS lanes_known,
                count(*) FILTER (WHERE NULLIF(btrim(maxspeed), '') IS NOT NULL) AS maxspeed_known,
                count(*) FILTER (WHERE NULLIF(btrim(oneway), '') IS NOT NULL) AS oneway_known,
                count(*) FILTER (WHERE NULLIF(btrim(toll), '') IS NOT NULL) AS toll_known,
                count(*) FILTER (WHERE bridge IS NOT NULL AND lower(bridge) NOT IN ('no', 'false', '0')) AS bridge_count,
                count(*) FILTER (WHERE tunnel IS NOT NULL AND lower(tunnel) NOT IN ('no', 'false', '0')) AS tunnel_count,
                count(*) FILTER (WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)) AS invalid_geometry,
                count(*) FILTER (WHERE geom IS NULL OR ST_IsEmpty(geom)) AS empty_geometry,
                count(*) FILTER (WHERE geom IS NOT NULL AND ST_GeometryType(geom) <> 'ST_LineString') AS unexpected_geometry_type,
                count(*) FILTER (WHERE geom IS NOT NULL AND ST_SRID(geom) <> 4326) AS unexpected_srid
            FROM public.road_segments WHERE source_id = :source_id
        """), {"source_id": source_id}).mappings().one()
        if counts["canonical_rows"] == 0:
            raise ValueError(f"No canonical road rows for source {source_slug}")
        sizes = connection.execute(text("""
            SELECT pg_relation_size('public.road_segments'::regclass) AS table_bytes,
                   pg_relation_size('public.road_segments_geom_gix'::regclass) AS spatial_index_bytes,
                   pg_indexes_size('public.road_segments'::regclass) AS all_indexes_bytes,
                   pg_total_relation_size('public.road_segments'::regclass) AS total_relation_bytes
        """)).mappings().one()
        staging_exists = connection.scalar(text(
            "SELECT to_regclass('staging_osm_roads.road_lines') IS NOT NULL"
        ))
        staging_rows = connection.scalar(text(
            "SELECT count(*) FROM staging_osm_roads.road_lines"
        )) if staging_exists else None
        sample_rows = connection.execute(text("""
            WITH points AS (
                SELECT ST_LineInterpolatePoint(geom, 0.5) AS point
                FROM public.road_segments WHERE source_id = :source_id
            ),
            ranked AS (
                SELECT point, row_number() OVER (ORDER BY ST_X(point), ST_Y(point)) AS row_number,
                       count(*) OVER () AS total_rows
                FROM points
            )
            SELECT ST_X(point) AS lon, ST_Y(point) AS lat
            FROM ranked
            WHERE row_number IN (1, (total_rows + 1) / 2, total_rows)
            ORDER BY row_number
        """), {"source_id": source_id}).all()
        database = {
            "staging_rows": staging_rows,
            "canonical_rows": counts["canonical_rows"],
            "extent": counts["extent"],
            "sizes_bytes": dict(sizes),
        }
        total = counts["canonical_rows"]
        quality = {
            "road_class": distribution(connection, source_id, "road_class"),
            "link_rows": counts["link_rows"],
            "non_link_rows": total - counts["link_rows"],
            "surface_known": counts["surface_known"],
            "surface_unknown": total - counts["surface_known"],
            "lanes_known": counts["lanes_known"],
            "lanes_unknown": total - counts["lanes_known"],
            "maxspeed_known": counts["maxspeed_known"],
            "maxspeed_unknown": total - counts["maxspeed_known"],
            "oneway_known": counts["oneway_known"],
            "oneway_unknown": total - counts["oneway_known"],
            "toll_known": counts["toll_known"],
            "toll_unknown": total - counts["toll_known"],
            "named": counts["named"], "unnamed": total - counts["named"],
            "bridge_count": counts["bridge_count"],
            "tunnel_count": counts["tunnel_count"],
            "invalid_geometry": counts["invalid_geometry"],
            "empty_geometry": counts["empty_geometry"],
            "unexpected_geometry_type": counts["unexpected_geometry_type"],
            "unexpected_srid": counts["unexpected_srid"],
        }
    engine.dispose()
    return dataset, {"database": database, "data_quality": quality}, [(r.lon, r.lat) for r in sample_rows]


def tile_coordinates(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    world = 2**zoom
    lat = max(min(lat, 85.05112878), -85.05112878)
    x = math.floor((lon + 180) / 360 * world)
    y = math.floor((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * world)
    return max(0, min(world - 1, x)), max(0, min(world - 1, y))


def sample_tiles(martin_url: str, locations: list[tuple[float, float]]) -> list[dict]:
    samples = []
    with httpx.Client(timeout=30, headers={
        "Accept": "application/x-protobuf", "Accept-Encoding": "gzip",
    }) as client:
        for zoom in ZOOMS:
            coordinates = sorted({tile_coordinates(lon, lat, zoom) for lon, lat in locations})
            for x, y in coordinates:
                started = time.perf_counter()
                sample = {"z": zoom, "x": x, "y": y, "http_status": None,
                          "wire_bytes": None, "decoded_payload_bytes": None,
                          "content_encoding": None, "feature_count": None,
                          "decode_error": None}
                try:
                    response = client.get(f"{martin_url.rstrip('/')}/road_segments/{zoom}/{x}/{y}")
                    sample.update({
                        "http_status": response.status_code,
                        "wire_bytes": response.num_bytes_downloaded,
                        "decoded_payload_bytes": len(response.content),
                        "content_encoding": response.headers.get("content-encoding"),
                        "feature_count": 0,
                    })
                    if response.status_code == 200 and response.content:
                        try:
                            decoded = mapbox_vector_tile.decode(response.content)
                            sample["feature_count"] = len(
                                decoded.get("road_segments", {}).get("features", [])
                            )
                        except (DecodeError, ValueError) as error:
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
    return {"download_bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def markdown(report: dict) -> str:
    dataset = report["dataset"]
    db = report["database"]
    quality = report["data_quality"]
    lines = [
        "# Road benchmark", "", "## Dataset", "",
        f"- URL: {dataset['url']}",
        f"- Filename: {dataset['input_filename']}",
        f"- Source slug: {dataset['slug']}",
        f"- Snapshot supplied: {dataset['snapshot_at'] or 'unknown'}",
        f"- Retrieved: {dataset['retrieved_at']}",
        f"- Download size: {dataset.get('download_bytes', 'not supplied')} bytes",
        f"- SHA-256: {dataset.get('sha256', 'not supplied')}",
        "", "## Timing", "",
        "| Stage | Seconds |", "|---|---:|",
    ]
    for stage, seconds in report["timing_seconds"].items():
        lines.append(f"| {stage} | {seconds:.3f} |" if seconds is not None else
                     f"| {stage} | not measured |")
    lines += [
        "", "## Database", "",
        f"- Staging rows: {db['staging_rows']}",
        f"- Canonical rows: {db['canonical_rows']}",
        f"- Extent (SRID 4326): {db['extent']}",
        "", "| Relation size | Bytes |", "|---|---:|",
    ]
    for name, size in db["sizes_bytes"].items():
        lines.append(f"| {name} | {size:,} ({size / 1024 / 1024:.2f} MiB) |")
    lines += ["", "## Data quality", "", "| Metric | Value |", "|---|---|"]
    for name, value in quality.items():
        lines.append(f"| {name} | {json.dumps(value, ensure_ascii=False).replace('|', '/')} |")
    lines += [
        "", "## Tile samples", "",
        "| z/x/y | HTTP | Wire bytes | Decoded payload bytes | Features | Seconds | Decode error | Error |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for tile in report["tile_samples"]:
        lines.append(
            f"| {tile['z']}/{tile['x']}/{tile['y']} | {tile['http_status']} | "
            f"{tile['wire_bytes']} | {tile['decoded_payload_bytes']} | "
            f"{tile['feature_count']} | {tile['request_seconds']} | "
            f"{(tile.get('decode_error') or '').replace('|', '/')} | "
            f"{tile.get('error', '').replace('|', '/')} |"
        )
    lines += [
        "", "## Observations", "",
        "- Samples use points on the imported road geometry at z5, z7, z9, z11, and z13.",
        "- No further optimization is selected from this benchmark alone.",
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

    dataset, measurements, locations = collect_database(args.source_slug)
    if args.input_path:
        dataset.update(file_facts(args.input_path))
    import_timings = json.loads(args.timings_json.read_text(encoding="utf-8")) if args.timings_json else {}
    timing = {
        "download": args.download_seconds,
        "postgis_startup": args.postgis_seconds,
        "alembic_migration": args.migration_seconds,
        "osm2pgsql_import": import_timings.get("osm2pgsql_import_seconds"),
        "canonical_normalization": import_timings.get("normalization_seconds"),
        "martin_startup": args.martin_seconds,
    }
    report = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "dataset": dataset, "timing_seconds": timing,
        **measurements,
        "tile_samples": sample_tiles(args.martin_url, locations),
    }
    args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_out.write_text(markdown(report), encoding="utf-8")
    quality = report["data_quality"]
    if any(quality[key] for key in (
        "invalid_geometry", "empty_geometry", "unexpected_geometry_type", "unexpected_srid"
    )):
        raise SystemExit("Canonical road geometry quality check failed; see benchmark report")
    if any(sample["http_status"] not in (200, 204) or sample.get("error")
           or sample.get("decode_error")
           for sample in report["tile_samples"]):
        raise SystemExit("Martin tile request failed; see benchmark report")
    print(f"Wrote {args.json_out} and {args.markdown_out}")


if __name__ == "__main__":
    main()
