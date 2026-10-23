from datetime import datetime, timezone

import pytest

from satquery.platform.capabilities import build_earth_capability_matrix
from satquery.platform.contracts import (
    ConnectorMetadata,
    DatasetMetadata,
    EarthCapabilitySnapshot,
    ObservationAsset,
    TemporalExtent,
)


def test_capability_matrix_is_deterministic_and_keeps_unknowns_unknown():
    connector = ConnectorMetadata(
        connector_id="fixture-weather",
        name="Fixture weather",
        version="2",
        provider_version="2026.1",
        authentication_schemes=("token",),
        supports_streaming=True,
        provider_metadata={"provider": "Example Institute", "native": {"x": 1}},
    )
    dataset = DatasetMetadata(
        connector_id="fixture-weather",
        dataset_id="surface-weather",
        version="r4",
        provider="Example Institute",
        variables=("air_temperature", "unmapped_sensor_value"),
        units={"air_temperature": "K"},
        modalities=("atmospheric",),
        temporal_coverage=TemporalExtent(
            start=datetime(2020, 1, 1, tzinfo=timezone.utc),
            end=datetime(2025, 1, 1, tzinfo=timezone.utc),
        ),
        historical_coverage=TemporalExtent(
            start=datetime(2020, 1, 1, tzinfo=timezone.utc),
            end=datetime(2025, 1, 1, tzinfo=timezone.utc),
        ),
        spatial_resolution=1000,
        resolution_unit="m",
        crs="EPSG:4326",
        quality_characteristics={"method": "provider-reported"},
        uncertainty_characteristics={"source": "not supplied"},
        access_policy={"limitations": ["rate limited"]},
        licensing="CC-BY-4.0",
        assets={"data": ObservationAsset(uri="https://example.test/data")},
        metadata={"native_collection_id": "WX-4"},
    )

    matrix = build_earth_capability_matrix((connector,), (dataset,))
    second = build_earth_capability_matrix((connector,), (dataset,))

    assert matrix.revision == second.revision
    assert len(matrix.entries) == 1
    entry = matrix.entries[0]
    assert entry.provider == "Example Institute"
    assert entry.provider_version == "2026.1"
    assert entry.authentication_required is True
    assert entry.authentication_schemes == ("token",)
    assert entry.supports_streaming is True
    assert entry.asset_references_declared is True
    assert entry.historical_coverage == dataset.historical_coverage
    assert entry.forecast_coverage is None
    assert entry.supports_forecast is None
    assert entry.confidence_available is None
    assert entry.field_provenance["canonical_variable"] == "earth-variable-ontology"
    assert entry.source_metadata["native_collection_id"] == "WX-4"
    public_matrix = matrix.model_dump(mode="json")
    public_json = str(public_matrix)
    assert "https://example.test/data" not in public_json
    assert "native_collection_id" not in public_json
    variables = {item.source_name: item for item in entry.variables}
    assert variables["air_temperature"].canonical_name == "air_temperature"
    assert variables["air_temperature"].unit == "K"
    assert variables["unmapped_sensor_value"].canonical_name is None
    modalities = {item.modality_id: item for item in matrix.modalities}
    assert modalities["atmospheric"].status == "registered"
    assert modalities["oceanic"].status == "not_registered"

    snapshot = matrix.capability_snapshot()
    assert snapshot.revision == matrix.revision
    assert snapshot.snapshot_sha256
    assert snapshot.entries[0].dataset_metadata is None
    assert snapshot.entries[0].source_metadata == {}
    assert snapshot.entries[0].provider_metadata == {}
    assert EarthCapabilitySnapshot.model_validate(
        snapshot.model_dump(mode="json")
    ) == snapshot
    snapshot_json = str(snapshot.model_dump(mode="json"))
    assert "https://example.test/data" not in snapshot_json
    assert "native_collection_id" not in snapshot_json
    changed_snapshot = snapshot.model_dump(mode="json")
    changed_snapshot["entries"][0]["connector_name"] = "Changed declaration"
    with pytest.raises(ValueError, match="capability snapshot digest"):
        EarthCapabilitySnapshot.model_validate(changed_snapshot)
    hidden_metadata_snapshot = snapshot.model_dump(mode="json")
    hidden_metadata_snapshot["entries"][0]["dataset_metadata"] = {
        "connector_id": "fixture-weather",
        "dataset_id": "surface-weather",
        "provider": "Example Institute",
        "assets": {"data": {"uri": "https://example.test/private"}},
    }
    with pytest.raises(ValueError, match="excluded raw metadata"):
        EarthCapabilitySnapshot.model_validate(hidden_metadata_snapshot)


def test_unbound_dataset_is_visible_without_claiming_an_adapter_is_available():
    dataset = DatasetMetadata(
        connector_id="not-loaded",
        dataset_id="declared-dem",
        provider="Survey Agency",
        variables=("elevation",),
        modalities=("geological",),
    )

    matrix = build_earth_capability_matrix((), (dataset,))

    entry = matrix.entries[0]
    assert entry.connector_registered is False
    assert entry.connector_available is None
    assert entry.supports_streaming is None
    assert entry.authentication_required is None
    assert (
        next(
            item for item in matrix.modalities if item.modality_id == "geological"
        ).status
        == "declared"
    )


def test_matrix_keeps_extension_modalities_without_inventing_labels():
    connector = ConnectorMetadata(
        connector_id="future-sensing",
        name="Future sensing implementation",
        version="1",
        modalities=("seismic_monitoring",),
    )

    matrix = build_earth_capability_matrix((connector,), ())

    modality = next(
        item for item in matrix.modalities if item.modality_id == "seismic_monitoring"
    )
    assert modality.status == "registered"
    assert modality.label is None
    assert modality.description is None


def test_authentication_and_licensing_remain_unknown_without_declarations():
    connector = ConnectorMetadata(
        connector_id="unknown-access",
        name="Unknown access requirements",
        version="1",
    )
    dataset = DatasetMetadata(
        connector_id=connector.connector_id,
        dataset_id="undeclared-access",
        provider="unknown",
    )

    entry = build_earth_capability_matrix((connector,), (dataset,)).entries[0]

    assert entry.authentication_required is None
    assert entry.licensing is None
    assert entry.supports_streaming is None
    assert entry.field_provenance["licensing"] == "unknown"
