"""Offline synthetic checks for the port benchmark sampler and report."""

import importlib.util
import json
import math
from pathlib import Path
import sqlite3
import sys

import pytest


PIPELINE = Path(__file__).resolve().parents[3] / "pipelines" / "ports"
sys.path.insert(0, str(PIPELINE))
spec = importlib.util.spec_from_file_location("port_benchmark", PIPELINE / "benchmark.py")
assert spec is not None and spec.loader is not None
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_xyz_clamping() -> None:
    assert benchmark.tile_coordinates(0, 0, 5) == (16, 16)
    assert benchmark.tile_coordinates(-180, 90, 5) == (0, 0)
    assert benchmark.tile_coordinates(180, -90, 5) == (31, 31)


@pytest.mark.parametrize(("zoom", "name", "expected"), [
    (4, "Named", False), (5, None, False), (5, "  ", False),
    (5, "Named", True), (6, "Named", True), (7, None, True),
    (9, "", True), (13, "Named", True),
])
def test_zoom_eligibility(zoom, name, expected) -> None:
    assert benchmark.eligible_at_zoom(zoom, name) is expected


def bucket_winner(tiles: list[tuple[int, int]], zoom: int) -> tuple[int, int, int]:
    connection = sqlite3.connect(":memory:")
    connection.create_function("LEAST", -1, min)
    connection.create_function("GREATEST", -1, max)
    connection.create_function("FLOOR", 1, math.floor)
    origin = benchmark.MERCATOR_ORIGIN
    world = 2**zoom
    params = {"world": world, "max_tile": world - 1,
              "origin": origin, "world_width": 2 * origin}
    values = []
    for index, (x, y) in enumerate(tiles):
        values.append(f"(:x{index}, :y{index})")
        params[f"x{index}"] = -origin + (x + 0.5) * 2 * origin / world
        params[f"y{index}"] = origin - (y + 0.5) * 2 * origin / world
    query = ("WITH projected_points(mercator_x, mercator_y) AS (VALUES "
             + ", ".join(values) + ") " + benchmark.HOTSPOT_BUCKET_SQL)
    result = connection.execute(query, params).fetchone()
    connection.close()
    assert result is not None
    return result


def test_hotspot_bucket_count_and_deterministic_ties() -> None:
    assert bucket_winner([(7, 8)] * 3 + [(2, 3)] * 2, 9) == (7, 8, 3)
    assert bucket_winner([(3, 2)] * 2 + [(2, 3)] * 2, 9) == (2, 3, 2)
    assert bucket_winner([(2, 4), (2, 3)], 9) == (2, 3, 1)


def test_representative_hotspot_dedup_and_serialization() -> None:
    location = (37.6, 55.72)
    hotspots = {z: {"x": benchmark.tile_coordinates(*location, z)[0],
                    "y": benchmark.tile_coordinates(*location, z)[1],
                    "candidate_point_count": z * 10} for z in benchmark.ZOOMS}
    plan = benchmark.sample_plan([location] * 3, hotspots)
    assert len(plan) == len(benchmark.ZOOMS)
    assert all(item["sample_kinds"] == ["representative", "density_hotspot"]
               for item in plan)
    assert json.loads(json.dumps(plan))[2]["candidate_point_count"] == 90


def test_martin_tile_checks_and_report_format(monkeypatch) -> None:
    requested = []

    class Response:
        status_code = 200
        content = b"tile"
        num_bytes_downloaded = 2
        headers = {"content-encoding": "gzip"}

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def get(self, url):
            requested.append(url)
            return Response()

    monkeypatch.setattr(benchmark.httpx, "Client", lambda **_: Client())
    monkeypatch.setattr(benchmark.mapbox_vector_tile, "decode", lambda _: {
        "ports": {"features": [{"id": 1, "geometry": {"type": "Point"},
                                "properties": {"name": "Port"}}]}
    })
    location = (37.6, 55.72)
    x, y = benchmark.tile_coordinates(*location, 9)
    samples = benchmark.sample_tiles("http://localhost:3000", [location], {
        9: {"x": x, "y": y, "candidate_point_count": 123},
    }, {1})
    assert len(requested) == 5
    assert all("/ports/" in url for url in requested)
    assert samples[2]["sample_kinds"] == ["representative", "density_hotspot"]
    assert samples[2]["candidate_point_count"] == 123
    assert all(s["feature_count"] == 1 and s["decode_error"] is None for s in samples)
    assert all(s["wire_bytes"] == 2 and s["decoded_payload_bytes"] == 4 for s in samples)

    row = {"id": 1, "source_object_type": "node", "source_object_id": 42,
           "name": "Port", "facility_class": "port", "water_context": None,
           "cargo": None, "operator": None, "longitude": 37.6, "latitude": 55.72}
    report = {
        "dataset": {"url": "https://example.org/ports.osm.pbf", "input_filename": "ports.osm.pbf",
                    "slug": "fixture", "name": "Fixture", "snapshot_at": None,
                    "retrieved_at": "2026-10-01"},
        "timing_seconds": {},
        "database": {"staging_rows": 1, "canonical_rows": 1,
                     "staging_matches_canonical": True, "staging_comparison_note": "Same source",
                     "extent": "BOX(0 0,1 1)", "sizes_bytes": {}},
        "facility_classes": {"port": {"count": 1, "percent": 100}},
        "source_object_types": {}, "metadata_coverage": {}, "quality": {},
        "audit_samples": {"by_facility_class": {"port": [row]},
                          "unnamed": [{"source_object_type": "way", "source_object_id": 8,
                                       "facility_class": "port", "longitude": 10,
                                       "latitude": 20}]},
        "tile_samples": samples,
    }
    rendered = benchmark.markdown(report)
    assert "representative, density hotspot | 123" in rendered
    assert "| 1 | node | 42 | Port | port" in rendered
    assert "| way | 8 | port | 10 | 20 |" in rendered
    assert "not production latency SLOs" in rendered


def test_mvt_semantic_failures(monkeypatch) -> None:
    class Response:
        status_code = 200
        content = b"tile"
        num_bytes_downloaded = 4
        headers = {}

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def get(self, _):
            return Response()

    monkeypatch.setattr(benchmark.httpx, "Client", lambda **_: Client())
    monkeypatch.setattr(benchmark.mapbox_vector_tile, "decode", lambda _: {
        "ports": {"features": [{"id": 999, "geometry": {"type": "Point"},
                                "properties": {"name": "Port"}}]}
    })
    samples = benchmark.sample_tiles("http://localhost", [(0, 0)], {}, {1})
    assert all("Noncanonical" in sample["decode_error"] for sample in samples)
