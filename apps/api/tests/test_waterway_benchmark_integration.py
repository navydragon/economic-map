"""Compare waterway midpoint hotspot SQL with independently bucketed fixture lines."""

from collections import Counter
import importlib.util
from pathlib import Path
import sys

from sqlalchemy import text

from app.database import get_engine


PIPELINE = Path(__file__).resolve().parents[3] / "pipelines" / "waterways"
sys.path.insert(0, str(PIPELINE))
spec = importlib.util.spec_from_file_location("waterway_benchmark_integration", PIPELINE / "benchmark.py")
assert spec is not None and spec.loader is not None
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_midpoint_hotspots_match_synthetic_canonical_segments() -> None:
    with get_engine().connect() as connection:
        rows = connection.execute(text("""
            SELECT ST_X(ST_LineInterpolatePoint(w.geom, 0.5)) AS lon,
                   ST_Y(ST_LineInterpolatePoint(w.geom, 0.5)) AS lat
            FROM public.waterway_segments AS w
            JOIN public.data_sources AS source ON source.id = w.source_id
            WHERE source.slug = 'ci-synthetic-waterways'
        """)).all()
        source_id = connection.scalar(text("""
            SELECT id FROM public.data_sources WHERE slug = 'ci-synthetic-waterways'
        """))
        assert len(rows) == 9 and source_id is not None
        for zoom in benchmark.ZOOMS:
            counts = Counter(benchmark.tile_coordinates(row.lon, row.lat, zoom)
                             for row in rows)
            (x, y), count = min(counts.items(), key=lambda item: (
                -item[1], item[0][0], item[0][1]))
            assert benchmark.density_hotspot(connection, source_id, zoom) == {
                "x": x, "y": y, "candidate_midpoint_count": count,
            }


def test_database_report_matches_synthetic_waterway_fixture() -> None:
    dataset, measurements, locations, hotspots, ids = benchmark.collect_database(
        "ci-synthetic-waterways")
    assert dataset["slug"] == "ci-synthetic-waterways"
    assert measurements["database"]["staging_rows"] == 9
    assert measurements["database"]["canonical_rows"] == 9
    assert measurements["database"]["staging_matches_canonical"] is True
    assert {key: value["count"] for key, value in
            measurements["waterway_classes"].items()} == {
                "river": 5, "canal": 3, "fairway": 1}
    assert measurements["naming_coverage"]["unnamed"]["count"] == 1
    assert measurements["navigation_coverage"]["explicit_navigation_any"]["count"] == 2
    assert measurements["explicit_navigation_any_count"] == 2
    assert measurements["navigation_matrix"]["canal"]["explicit_navigation_any"] == 2
    assert measurements["value_distributions"]["cemt_class"] == [{"value": "II", "count": 1}]
    assert all(value == 0 for value in measurements["geometry_quality"].values())
    assert measurements["segment_complexity"]["total_vertices"] >= 18
    assert measurements["segment_complexity"]["p95_length_m"] > 0
    assert len(measurements["audit_samples"]["explicit_navigation"]) == 2
    assert len(locations) == 3 and len(hotspots) == len(benchmark.ZOOMS)
    assert len(ids) == 9
