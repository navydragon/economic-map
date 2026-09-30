import importlib.util
import json
import math
from pathlib import Path
import sqlite3
import sys

import pytest


ROAD_PIPELINE = Path(__file__).resolve().parents[3] / "pipelines" / "roads"
sys.path.insert(0, str(ROAD_PIPELINE))
spec = importlib.util.spec_from_file_location("road_benchmark", ROAD_PIPELINE / "benchmark.py")
assert spec is not None and spec.loader is not None
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_tile_coordinates_clamp_web_mercator_edges() -> None:
    assert benchmark.tile_coordinates(0, 0, 5) == (16, 16)
    assert benchmark.tile_coordinates(-180, 0, 5) == (0, 16)
    assert benchmark.tile_coordinates(180, 0, 5) == (31, 16)
    assert benchmark.tile_coordinates(0, 90, 5) == (16, 0)
    assert benchmark.tile_coordinates(0, -90, 5) == (16, 31)


@pytest.mark.parametrize(("zoom", "classes", "links"), [
    (4, (), False),
    (5, ("motorway", "trunk"), False),
    (6, ("motorway", "trunk", "primary"), False),
    (7, ("motorway", "trunk", "primary", "secondary"), False),
    (9, benchmark.ROAD_CLASSES, False),
    (10, benchmark.ROAD_CLASSES, True),
    (13, benchmark.ROAD_CLASSES, True),
])
def test_hotspot_semantic_eligibility(zoom, classes, links) -> None:
    assert benchmark.eligible_road_classes(zoom) == (classes, links)


def bucket_winner(tile_coordinates: list[tuple[int, int]], zoom: int) -> tuple[int, int, int]:
    """Run the production bucket/rank SQL on synthetic projected midpoints."""
    connection = sqlite3.connect(":memory:")
    connection.create_function("LEAST", -1, min)
    connection.create_function("GREATEST", -1, max)
    connection.create_function("FLOOR", 1, math.floor)
    world = 2**zoom
    origin = benchmark.MERCATOR_ORIGIN
    params = {"world": world, "max_tile": world - 1,
              "origin": origin, "world_width": 2 * origin}
    values = []
    for index, (x, y) in enumerate(tile_coordinates):
        values.append(f"(:x{index}, :y{index})")
        params[f"x{index}"] = -origin + (x + 0.5) * 2 * origin / world
        params[f"y{index}"] = origin - (y + 0.5) * 2 * origin / world
    query = ("WITH projected_midpoints(mercator_x, mercator_y) AS (VALUES "
             + ", ".join(values) + ") " + benchmark.HOTSPOT_BUCKET_SQL)
    winner = connection.execute(query, params).fetchone()
    connection.close()
    assert winner is not None
    return winner


def test_hotspot_bucket_counts_and_tie_breaking() -> None:
    assert bucket_winner([(7, 8)] * 3 + [(2, 3)] * 2, 9) == (7, 8, 3)
    assert bucket_winner([(3, 2)] * 2 + [(2, 3)] * 2, 9) == (2, 3, 2)
    assert bucket_winner([(2, 4), (2, 3)], 9) == (2, 3, 1)


def test_hotspot_bucket_clamps_xyz_coordinates() -> None:
    assert bucket_winner([(-1, 40)], 5) == (0, 31, 1)


def test_representative_and_hotspot_planning() -> None:
    location = (37.6, 55.72)
    hotspots = {}
    for zoom in benchmark.ZOOMS:
        x, y = benchmark.tile_coordinates(*location, zoom)
        hotspots[zoom] = {"x": x + 1, "y": y, "candidate_midpoint_count": zoom * 10}
    plan = benchmark.sample_plan([location, location], hotspots)
    assert len(plan) == 10
    assert sum("representative" in item["sample_kinds"] for item in plan) == 5
    assert sum("density_hotspot" in item["sample_kinds"] for item in plan) == 5
    assert all(item["candidate_midpoint_count"] == item["z"] * 10
               for item in plan if "density_hotspot" in item["sample_kinds"])


def test_road_tile_samples_use_production_source_and_zooms(monkeypatch) -> None:
    requested_urls = []

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
            requested_urls.append(url)
            return Response()

    monkeypatch.setattr(benchmark.httpx, "Client", lambda **_: Client())
    monkeypatch.setattr(benchmark.mapbox_vector_tile, "decode", lambda _: {
        "road_segments": {"features": [{}, {}]}
    })

    location = (37.6, 55.72)
    x, y = benchmark.tile_coordinates(*location, 9)
    samples = benchmark.sample_tiles("http://localhost:3000", [location], {
        9: {"x": x, "y": y, "candidate_midpoint_count": 1234},
    })
    assert [sample["z"] for sample in samples] == [5, 7, 9, 11, 13]
    assert len(requested_urls) == 5  # z9 serves both roles with one request.
    assert all("/road_segments/" in url for url in requested_urls)
    assert samples[2]["sample_kinds"] == ["representative", "density_hotspot"]
    assert samples[2]["candidate_midpoint_count"] == 1234
    assert json.loads(json.dumps(samples))[2]["candidate_midpoint_count"] == 1234
    assert all(sample["feature_count"] == 2 and sample["decode_error"] is None
               for sample in samples)
    assert all(sample["wire_bytes"] == 2 and sample["decoded_payload_bytes"] == 4
               for sample in samples)

    report = {
        "dataset": {"url": "https://example.org/roads.osm.pbf", "input_filename": "roads.osm.pbf",
                    "slug": "fixture", "snapshot_at": None, "retrieved_at": "2026-09-30"},
        "timing_seconds": {},
        "database": {"staging_rows": 1, "canonical_rows": 1,
                     "extent": "BOX(0 0,1 1)", "sizes_bytes": {}},
        "data_quality": {}, "tile_samples": samples,
    }
    markdown = benchmark.markdown(report)
    assert "Sample kinds | Candidate midpoints" in markdown
    assert "representative, density hotspot | 1234" in markdown
    assert "not an exhaustive worst-case search" in markdown
