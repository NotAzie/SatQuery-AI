"""Evidence-preserving quality assessments for canonical observations."""

from __future__ import annotations

from datetime import datetime, timezone
from importlib import import_module
import math
from typing import Iterable, Literal, Optional

from .contracts import (
    Observation,
    ObservationQuality,
    QualityQuery,
    QualityRecord,
)
from .temporal import freshness_seconds
from .ontology import canonical_variable_name


def assess_observation(
    observation: Observation,
    *,
    expected_variables: Optional[Iterable[str]] = None,
    now: Optional[datetime] = None,
) -> ObservationQuality:
    """Summarize known quality without manufacturing missing quality values."""
    expected = tuple(
        canonical_variable_name(variable).casefold()
        for variable in (expected_variables or ())
    )
    completeness: Optional[float] = None
    if expected:
        measured_variables = {
            canonical_variable_name(variable).casefold(): value
            for variable, value in observation.measured_variables.items()
        }
        measured_variables.update({
            item.canonical_variable.casefold(): item.value
            for item in observation.canonical_measurements
            if item.semantic_status == "resolved"
        })
        present = sum(
            1
            for variable in expected
            if variable in measured_variables and _has_value(measured_variables[variable])
        )
        completeness = present / len(expected)
    observed_at = observation.observed_at
    if observed_at is None and observation.temporal_extent is not None:
        observed_at = observation.temporal_extent.end
    freshness = freshness_seconds(
        observation.model_copy(
            update={
                "observed_at": observed_at,
                "temporal_extent": observation.temporal_extent,
            }
        ),
        now=now or datetime.now(timezone.utc),
    )
    source_quality = dict(observation.quality)
    provider_quality_score = _normalized_quality_score(source_quality)
    lineage: list[dict[str, object]] = []
    for key, value in observation.provenance.items():
        lineage.append({"source": key, "record": value})
    reproducibility = "unknown"
    if observation.reproducibility:
        reproducibility = (
            "available"
            if observation.source_id is not None
            else "incomplete"
        )
    return ObservationQuality(
        # Keep quality dimensions separate. A confidence value and a
        # completeness ratio are not interchangeable measurements, so the
        # platform does not combine them into a synthetic score.
        quality_score=provider_quality_score,
        completeness=completeness,
        uncertainty=dict(observation.uncertainty),
        confidence=observation.confidence,
        provider_quality_score=provider_quality_score,
        freshness_seconds=freshness,
        provider_quality=source_quality,
        lineage=tuple(lineage),
        reproducibility=reproducibility,
        validation_status=_validate_geometry(observation),
    )


class ObservationQualityService:
    """Assess and query observation quality independently of acquisition."""

    def assess(
        self,
        observation: Observation,
        *,
        expected_variables: Optional[Iterable[str]] = None,
        now: Optional[datetime] = None,
    ) -> QualityRecord:
        return QualityRecord(
            observation_id=observation.observation_id,
            assessment=assess_observation(
                observation,
                expected_variables=expected_variables,
                now=now,
            ),
        )

    def filter(
        self,
        records: Iterable[QualityRecord],
        query: QualityQuery,
    ) -> tuple[QualityRecord, ...]:
        return tuple(
            record
            for record in records
            if _matches_quality(record.assessment, query)
        )


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, dict) and "value" in value:
        return value["value"] is not None
    return True


def _matches_quality(assessment: ObservationQuality, query: QualityQuery) -> bool:
    if query.minimum_quality_score is not None and (
        assessment.quality_score is None
        or assessment.quality_score < query.minimum_quality_score
    ):
        return False
    for minimum, actual in (
        (query.minimum_completeness, assessment.completeness),
        (query.minimum_confidence, assessment.confidence),
        (query.minimum_provider_quality, assessment.provider_quality_score),
    ):
        if minimum is not None and (actual is None or actual < minimum):
            return False
    if query.maximum_freshness_seconds is not None:
        age = assessment.freshness_seconds
        if age is None or age < 0 or age > query.maximum_freshness_seconds:
            return False
    if (
        query.validation_status is not None
        and assessment.validation_status != query.validation_status
    ):
        return False
    return True


def _normalized_quality_score(quality: dict[str, object]) -> Optional[float]:
    score = quality.get("normalized_score")
    if (
        isinstance(score, (int, float))
        and not isinstance(score, bool)
        and math.isfinite(score)
        and 0 <= score <= 1
    ):
        return float(score)
    return None


def _validate_geometry(
    observation: Observation,
) -> Literal["valid", "invalid", "not_assessed"]:
    if observation.bbox is not None:
        if not all(math.isfinite(value) for value in observation.bbox):
            return "invalid"
        if len(observation.bbox) == 4:
            min_x, min_y, max_x, max_y = observation.bbox
        else:
            min_x, min_y, _, max_x, max_y, _ = observation.bbox
        geographic_crs = (observation.crs or "").casefold() in {
            "crs84",
            "ogc:crs84",
            "epsg:4326",
            "urn:ogc:def:crs:ogc:1.3:crs84",
        }
        if min_y > max_y or (min_x > max_x and not geographic_crs):
            return "invalid"
    if observation.geometry is None:
        return "valid"
    geometry_type = observation.geometry.get("type")
    coordinate_key = (
        "geometries" if geometry_type == "GeometryCollection" else "coordinates"
    )
    coordinates = observation.geometry.get(coordinate_key)
    if not isinstance(geometry_type, str) or not isinstance(coordinates, list):
        return "invalid"
    if geometry_type == "Point":
        if len(coordinates) < 2 or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            for value in coordinates[:2]
        ):
            return "invalid"
        return "valid"
    try:
        shape = import_module("shapely.geometry").shape
    except ImportError:
        return "not_assessed"
    try:
        geometry = shape(observation.geometry)
    except (TypeError, ValueError):
        return "invalid"
    return "valid" if not geometry.is_empty and geometry.is_valid else "invalid"
