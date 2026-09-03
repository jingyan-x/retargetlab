import pytest

from retargetlab.io.probe.parquet import probe_parquet


def test_parquet_probe_records_schema_without_values(tmp_path) -> None:
    pa = pytest.importorskip("pyarrow")
    parquet = pytest.importorskip("pyarrow.parquet")
    values = pa.array([0.0, 0.01])
    vector_values = pa.array([0.0, 1.0, 2.0, 3.0])
    vector = pa.FixedSizeListArray.from_arrays(vector_values, list_size=2)
    path = tmp_path / "fixture.parquet"
    parquet.write_table(
        pa.table({"timestamp": values, "observation.state": vector}),
        path,
    )

    manifest = probe_parquet(
        path,
        dataset_alias="synthetic-fixture",
        source_revision="v1",
    )
    assert manifest.row_count == 2
    assert manifest.source_sha256 is not None
    assert manifest.fields["timestamp"].shape == ()
    assert manifest.fields["observation.state"].shape == (2,)
    assert "values" not in repr(manifest)
