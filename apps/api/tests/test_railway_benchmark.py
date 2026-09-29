from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "pipelines" / "railways"))

import benchmark  # noqa: E402


def test_tile_samples_follow_imported_geometry_at_multiple_zooms(monkeypatch) -> None:
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

        def get(self, _):
            return Response()

    monkeypatch.setattr(benchmark.httpx, "Client", lambda **_: Client())
    monkeypatch.setattr(benchmark.mapbox_vector_tile, "decode", lambda _: {
        "railway_segments": {"features": [{}, {}]}
    })

    samples = benchmark.sample_tiles("http://localhost:3000", [(37.6, 55.72)])
    assert [sample["z"] for sample in samples] == [5, 7, 9, 11, 13]
    assert (samples[1]["x"], samples[1]["y"]) == benchmark.tile_coordinates(37.6, 55.72, 7)
    assert all(sample["feature_count"] == 2 for sample in samples)
    assert all(sample["wire_bytes"] == 2 and sample["decoded_payload_bytes"] == 4 for sample in samples)
