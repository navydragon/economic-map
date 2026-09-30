"""Compare the real PostGIS hotspot query with synthetic fixture calculations."""

from collections import Counter
import importlib.util
from pathlib import Path
import sys

from sqlalchemy import text

from app.database import get_engine


ROAD_PIPELINE = Path(__file__).resolve().parents[3] / "pipelines" / "roads"
sys.path.insert(0, str(ROAD_PIPELINE))
spec = importlib.util.spec_from_file_location("road_benchmark_integration", ROAD_PIPELINE / "benchmark.py")
assert spec is not None and spec.loader is not None
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_density_hotspot_matches_fixture_midpoint_buckets() -> None:
    with get_engine().connect() as connection:
        rows = connection.execute(text("""
            SELECT r.road_class, r.is_link,
                   ST_X(ST_LineInterpolatePoint(r.geom, 0.5)) AS lon,
                   ST_Y(ST_LineInterpolatePoint(r.geom, 0.5)) AS lat
            FROM public.road_segments AS r
            JOIN public.data_sources AS source ON source.id = r.source_id
            WHERE source.slug = 'ci-synthetic-roads'
        """)).all()
        source_id = connection.scalar(text("""
            SELECT id FROM public.data_sources WHERE slug = 'ci-synthetic-roads'
        """))
        assert len(rows) == 10 and source_id is not None
        for zoom in benchmark.ZOOMS:
            classes, include_links = benchmark.eligible_road_classes(zoom)
            counts = Counter(
                benchmark.tile_coordinates(row.lon, row.lat, zoom)
                for row in rows
                if row.road_class in classes and (include_links or not row.is_link)
            )
            (x, y), count = min(counts.items(), key=lambda item: (
                -item[1], item[0][0], item[0][1]
            ))
            assert benchmark.density_hotspot(connection, source_id, zoom) == {
                "x": x, "y": y, "candidate_midpoint_count": count,
            }
