"""Offline synthetic tests for waterway benchmark planning and reporting."""

import importlib.util
import json
import math
from pathlib import Path
import sqlite3
import sys

import pytest


PIPELINE = Path(__file__).resolve().parents[3] / "pipelines" / "waterways"
sys.path.insert(0, str(PIPELINE))
spec = importlib.util.spec_from_file_location("waterway_benchmark", PIPELINE / "benchmark.py")
assert spec is not None and spec.loader is not None
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_xyz_clamping_and_zoom_plan() -> None:
    assert benchmark.ZOOMS == (5, 7, 9, 11, 13)
    assert benchmark.tile_coordinates(0, 0, 5) == (16, 16)
    assert benchmark.tile_coordinates(-180, 90, 5) == (0, 0)
    assert benchmark.tile_coordinates(180, -90, 5) == (31, 31)


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
    query = ("WITH projected_midpoints(mercator_x, mercator_y) AS (VALUES "
             + ", ".join(values) + ") " + benchmark.HOTSPOT_BUCKET_SQL)
    result = connection.execute(query, params).fetchone()
    connection.close()
    assert result is not None
    return result


def test_midpoint_hotspot_ranking_and_ties() -> None:
    assert bucket_winner([(7, 8)] * 3 + [(2, 3)] * 2, 9) == (7, 8, 3)
    assert bucket_winner([(3, 2)] * 2 + [(2, 3)] * 2, 9) == (2, 3, 2)
    assert bucket_winner([(2, 4), (2, 3)], 9) == (2, 3, 1)
    assert bucket_winner([(-1, 40)], 5) == (0, 31, 1)


def test_representative_hotspot_roles_dedup_and_serialization() -> None:
    location = (37.6, 55.72)
    hotspots = {zoom: {"x": benchmark.tile_coordinates(*location, zoom)[0],
                       "y": benchmark.tile_coordinates(*location, zoom)[1],
                       "candidate_midpoint_count": zoom * 10}
                for zoom in benchmark.ZOOMS}
    plan = benchmark.sample_plan([location] * 3, hotspots)
    assert [item["z"] for item in plan] == list(benchmark.ZOOMS)
    assert all(item["sample_kinds"] == ["representative", "density_hotspot"]
               for item in plan)
    assert json.loads(json.dumps(plan))[2]["candidate_midpoint_count"] == 90


def test_navigation_coverage_matrix_and_top_values() -> None:
    rows = [
        {"waterway_class": "river", "boat_access": None, "ship_access": None},
        {"waterway_class": "river", "boat_access": "yes", "ship_access": None},
        {"waterway_class": "canal", "cemt_class": "II", "motorboat_access": "permissive",
         "intermittent": False},
        {"waterway_class": "fairway", "ship_access": "designated"},
    ]
    coverage, matrix = benchmark.navigation_counts(rows)
    assert coverage["explicit_navigation_any"] == {"count": 3, "percentage": 75.0}
    assert coverage["intermittent"] == {"count": 1, "percentage": 25.0}
    assert matrix["river"] == {"explicit_navigation_any": 1, "cemt_class": 0,
                                "ship_access": 0, "motorboat_access": 0, "boat_access": 1}
    assert matrix["canal"]["cemt_class"] == 1
    assert matrix["fairway"]["ship_access"] == 1
    assert benchmark.top_values(["II", "I", "II", "III", "I", None, ""], limit=2) == [
        {"value": "I", "count": 2}, {"value": "II", "count": 2}]


def test_martin_samples_and_report(monkeypatch) -> None:
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
    def decoded(_):
        zoom = int(requested[-1].split("/waterway_segments/")[1].split("/")[0])
        feature = {"geometry": {"type": "LineString"},
                   "properties": {"waterway_class": "river"}}
        if zoom >= 9:
            feature.update({"id": 1})
            feature["properties"]["boat_access"] = "yes"
        return {"waterway_segments": {"features": [feature]}}

    monkeypatch.setattr(benchmark.mapbox_vector_tile, "decode", decoded)
    location = (37.6, 55.72)
    hotspots = {zoom: {"x": benchmark.tile_coordinates(*location, zoom)[0],
                       "y": benchmark.tile_coordinates(*location, zoom)[1],
                       "candidate_midpoint_count": 123 if zoom == 9 else zoom}
                for zoom in benchmark.ZOOMS}
    samples = benchmark.sample_tiles("http://localhost:3000", [location], hotspots, {1})
    assert len(requested) == 5
    assert all("/waterway_segments/" in url for url in requested)
    assert samples[2]["sample_kinds"] == ["representative", "density_hotspot"]
    assert samples[2]["candidate_midpoint_count"] == 123
    assert all(s["feature_count"] == 1 and s["decode_error"] is None for s in samples)

    audit_row = {key: None for key in (
        "id", "source_object_id", "name", "ref", "waterway_class", "boat_access",
        "motorboat_access", "ship_access", "oneway_boat", "cemt_class", "usage",
        "service", "width", "intermittent", "tidal", "operator")}
    audit_row.update({"id": 1, "source_object_id": 42, "name": "Synthetic River",
                      "waterway_class": "river", "boat_access": "yes"})
    report = {
        "dataset": {"url": "https://example.org/waterways.osm.pbf",
                    "input_filename": "waterways.osm.pbf", "slug": "fixture",
                    "name": "Fixture", "snapshot_at": None, "retrieved_at": "2026-10-02"},
        "timing_seconds": {},
        "database": {"staging_rows": 1, "canonical_rows": 1,
                     "staging_matches_canonical": True, "staging_comparison_note": "same",
                     "extent": "BOX(0 0,1 1)", "sizes_bytes": {}},
        "waterway_classes": {"river": {"count": 1, "percentage": 100}},
        "naming_coverage": {}, "navigation_coverage": {},
        "navigation_matrix": {"river": {"explicit_navigation_any": 1, "cemt_class": 0,
                                        "ship_access": 0, "motorboat_access": 0, "boat_access": 1}},
        "value_distributions": {"boat_access": [{"value": "yes", "count": 1}]},
        "geometry_quality": {}, "segment_complexity": {},
        "audit_samples": {"by_class": {"river": [audit_row]},
                          "explicit_navigation": [audit_row]},
        "tile_samples": samples,
    }
    rendered = benchmark.markdown(report)
    assert "representative, density hotspot | 123" in rendered
    assert "| z9 | 123 | 1 | 2 | 4 |" in rendered
    assert "Synthetic River" in rendered
    assert "| yes | 1 |" in rendered
    assert "not the exact densest tile" in rendered


@pytest.mark.parametrize(("decoded", "error"), [
    ({"wrong": {"features": []}}, "source layer"),
    ({"waterway_segments": {"features": [{"id": 7, "geometry": {"type": "LineString"},
                                         "properties": {"waterway_class": "river"}}]}}, "Noncanonical"),
    ({"waterway_segments": {"features": [{"id": 1, "geometry": {"type": "Point"},
                                         "properties": {"waterway_class": "river"}}]}}, "linear"),
    ({"waterway_segments": {"features": [{"id": 1, "geometry": {"type": "LineString"},
                                         "properties": {"waterway_class": "river", "secret": "x"}}]}}, "property"),
    ({"waterway_segments": {"features": [{"id": 1, "geometry": {"type": "LineString"},
                                         "properties": {"waterway_class": "river", "tidal": "yes"}}]}}, "type"),
])
def test_mvt_contract_failures(monkeypatch, decoded, error) -> None:
    monkeypatch.setattr(benchmark, "ZOOMS", (9,))
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
    monkeypatch.setattr(benchmark.mapbox_vector_tile, "decode", lambda _: decoded)
    samples = benchmark.sample_tiles("http://localhost", [(0, 0)], {}, {1})
    assert all(error in sample["decode_error"] for sample in samples)


def test_low_zoom_benchmark_rejects_segment_details_without_requiring_id(monkeypatch) -> None:
    monkeypatch.setattr(benchmark, "ZOOMS", (5,))

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
    properties = {"waterway_class": "river", "name": "Synthetic River"}
    monkeypatch.setattr(benchmark.mapbox_vector_tile, "decode", lambda _: {
        "waterway_segments": {"features": [
            {"geometry": {"type": "LineString"}, "properties": properties}]}
    })
    sample = benchmark.sample_tiles("http://localhost", [(0, 0)], {}, {1})[0]
    assert sample["decode_error"] is None
    properties["boat_access"] = "yes"
    sample = benchmark.sample_tiles("http://localhost", [(0, 0)], {}, {1})[0]
    assert "Unexpected waterway MVT property" in sample["decode_error"]
