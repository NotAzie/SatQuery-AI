"""Deterministic, auditable translation from investigation text to EarthQuery plans.

This module does not call a model, geocoder, or provider. It extracts only
explicit ontology terms, explicit coordinates/regions, and well-defined time
expressions. Anything else remains unresolved for clarification.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import uuid
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Literal, Optional

from pydantic import Field, model_validator

from ..errors import ValidationError
from .capabilities import EarthCapabilityMatrix
from .contracts import (
    Contract,
    DatasetReference,
    EarthCapabilitySnapshot,
    EarthQuery,
    PerceptionPlan,
)
from .modalities import SensingModalityRegistry
from .ontology import EARTH_VARIABLE_ONTOLOGY, EarthVariableOntology

PLANNER_ID = "satquery.deterministic-investigation-planner"
PLANNER_VERSION = "1.0.0"


class ObjectiveExtraction(Contract):
    objective_type: Literal[
        "observe", "measure", "detect", "map", "monitor", "compare", "assess", "investigate"
    ]
    statement: str = Field(min_length=1)
    source_text: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class VariableMention(Contract):
    source_text: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    canonical_variable: Optional[str] = None
    candidate_variables: tuple[str, ...] = ()
    ontology_concept_id: Optional[str] = None
    ontology_uri: Optional[str] = None
    resolution: Literal["resolved", "ambiguous"]


class PhenomenonMention(Contract):
    source_text: str = Field(min_length=1)
    concept_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class GeographicMention(Contract):
    source_text: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    resolution: Literal["explicit_coordinates", "explicit_bbox", "explicit_geometry", "declared_region", "unresolved"]
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    bbox: Optional[tuple[float, ...]] = None
    geometry: Optional[dict[str, Any]] = None
    region: Optional[str] = None


class TimeInterpretation(Contract):
    source_text: Optional[str] = None
    resolution: Literal["explicit", "relative", "missing", "ambiguous"]
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    reference_time: datetime
    interpretation: Optional[str] = None


class CandidateHypothesis(Contract):
    statement: str = Field(min_length=1)
    source_text: str = Field(min_length=1)
    origin: Literal["explicit", "question_derived"]
    evidential_status: Literal["unassessed"] = "unassessed"


class EvidenceRequirement(Contract):
    requirement_id: str = Field(min_length=1)
    evidence_type: Literal["variable", "modality", "spatial_scope", "temporal_scope"]
    target: str = Field(min_length=1)
    required: bool = True
    rationale: str = Field(min_length=1)


class MissingInformation(Contract):
    field: str = Field(min_length=1)
    question: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    candidate_values: tuple[str, ...] = ()


class PlannerAssumption(Contract):
    field: str = Field(min_length=1)
    value: str = Field(min_length=1)
    source: Literal["explicit_request", "deterministic_interpretation"]
    rationale: str = Field(min_length=1)


class DeclaredCostEstimate(Contract):
    status: Literal["declared", "unknown"]
    amount: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = None
    pricing_unit: Optional[str] = None
    source_dataset_ids: tuple[str, ...] = ()
    explanation: str


class ObservationQualityExpectation(Contract):
    dataset_id: str = Field(min_length=1)
    declared_quality: dict[str, Any] = Field(default_factory=dict)
    declared_uncertainty: dict[str, Any] = Field(default_factory=dict)
    confidence_available: Optional[bool] = None
    basis: Literal["dataset_declaration", "unknown"]


class ProviderAssessment(Contract):
    connector_id: str = Field(min_length=1)
    provider: Optional[str] = None
    provider_version: Optional[str] = None
    registered: bool
    declared_available: Optional[bool] = None
    declared_health: str = "unknown"
    confidence: Optional[float] = None
    confidence_status: Literal["not_declared"] = "not_declared"
    basis: str = "connector and capability declarations only; no active probe was run"


class PlannedObservationStep(Contract):
    step_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    requested_modalities: tuple[str, ...] = ()
    requested_variables: tuple[str, ...] = ()
    earth_query: EarthQuery
    perception_plan: PerceptionPlan
    selected_datasets: tuple[DatasetReference, ...] = ()
    selected_implementations: tuple[str, ...] = ()
    provider_assessments: tuple[ProviderAssessment, ...] = ()
    quality_expectations: tuple[ObservationQualityExpectation, ...] = ()
    cost_estimate: DeclaredCostEstimate
    dependencies: tuple[str, ...] = ()


class CandidateInvestigationPlan(Contract):
    candidate_plan_id: str = Field(min_length=1)
    interpretation: str = Field(min_length=1)
    selected_variables: tuple[str, ...] = ()
    earth_query: EarthQuery
    perception_plan: PerceptionPlan
    selected_datasets: tuple[DatasetReference, ...] = ()
    selected_implementations: tuple[str, ...] = ()
    provider_assessments: tuple[ProviderAssessment, ...] = ()
    quality_expectations: tuple[ObservationQualityExpectation, ...] = ()
    cost_estimate: DeclaredCostEstimate
    steps: tuple[PlannedObservationStep, ...] = ()


class InvestigationPlan(Contract):
    """A proposal for an investigation; creation does not acquire observations."""

    plan_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1)
    planner_id: str = PLANNER_ID
    planner_version: str = PLANNER_VERSION
    question: str = Field(min_length=1)
    objective: Optional[ObjectiveExtraction] = None
    hypotheses: tuple[CandidateHypothesis, ...] = ()
    geographic_entities: tuple[GeographicMention, ...] = ()
    time_interpretation: TimeInterpretation
    variables: tuple[VariableMention, ...] = ()
    phenomena: tuple[PhenomenonMention, ...] = ()
    requested_modalities: tuple[str, ...] = ()
    required_evidence: tuple[EvidenceRequirement, ...] = ()
    candidate_plans: tuple[CandidateInvestigationPlan, ...] = ()
    missing_information: tuple[MissingInformation, ...] = ()
    assumptions: tuple[PlannerAssumption, ...] = ()
    status: Literal["ready", "needs_clarification", "no_capability", "invalid"]
    selected_candidate_plan_id: Optional[str] = None
    capability_matrix_revision: str
    capability_snapshot: Optional[EarthCapabilitySnapshot] = None
    reproducibility: dict[str, Any] = Field(default_factory=dict)
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_capability_snapshot_revision(self) -> "InvestigationPlan":
        if (
            self.capability_snapshot is not None
            and self.capability_matrix_revision != self.capability_snapshot.revision
        ):
            raise ValueError("capability snapshot revision does not match the investigation plan")
        return self


class InvestigationPlanner:
    """Compose ontology parsing, scope resolution, and capability-aware proposals."""

    def __init__(
        self,
        *,
        modality_registry: SensingModalityRegistry,
        capability_matrix: Callable[[], EarthCapabilityMatrix],
        capability_plan: Callable[[EarthQuery], PerceptionPlan],
        ontology: EarthVariableOntology = EARTH_VARIABLE_ONTOLOGY,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_candidate_plans: int = 8,
    ) -> None:
        if max_candidate_plans < 1:
            raise ValueError("max_candidate_plans must be positive")
        self.modality_registry = modality_registry
        self.capability_matrix = capability_matrix
        self.capability_plan = capability_plan
        self.ontology = ontology
        self.clock = clock
        self.max_candidate_plans = max_candidate_plans

    def plan(
        self,
        question: str,
        *,
        earth_query: Optional[EarthQuery] = None,
    ) -> InvestigationPlan:
        question = question.strip()
        if not question:
            raise ValidationError("An investigation question must not be empty.")
        reference_time = self.clock()
        if reference_time.tzinfo is None:
            raise ValueError("planner clock must return a timezone-aware datetime")
        reference_time = reference_time.astimezone(timezone.utc)
        matrix = self.capability_matrix()
        request_document = {
            "question": question,
            "earth_query": earth_query.model_dump(mode="json") if earth_query else None,
        }
        request_digest = hashlib.sha256(
            json.dumps(request_document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        ontology_revision = _ontology_revision(self.ontology)
        plan_id = _stable_identifier(
            f"{PLANNER_VERSION}:{request_digest}:{reference_time.isoformat()}:{matrix.revision}:{ontology_revision}"
        )

        objective = _extract_objective(question)
        hypotheses = _extract_hypotheses(question)
        variables = _extract_variables(question, self.ontology)
        phenomena = _extract_phenomena(question, self.ontology)
        modalities = _extract_modalities(question, self.modality_registry)
        geographic, spatial_values, geography_missing = _extract_geography(
            question, matrix
        )
        temporal, temporal_assumption = _extract_time(question, reference_time)

        resolved_variables = tuple(
            mention.canonical_variable
            for mention in variables
            if mention.canonical_variable is not None
        )
        ambiguous = tuple(
            mention for mention in variables if mention.resolution == "ambiguous"
        )
        inferred_modalities = {
            modality
            for variable in resolved_variables
            for modality in self.modality_registry.for_variable(variable)
        }
        phenomenon_modalities = set()
        for phenomenon in phenomena:
            for modality in self.modality_registry.modalities():
                if phenomenon.concept_id in modality.ontology_concepts:
                    inferred_modalities.add(modality.modality_id)
                    phenomenon_modalities.add(modality.modality_id)
        requested_modalities = tuple(sorted(set(modalities) | inferred_modalities))

        if earth_query is not None:
            # Explicit structured criteria are authoritative; NLP findings remain
            # annotations and are never silently merged into the user's query.
            requested_variables = earth_query.requested_variables
            explicit_variables = set(earth_query.requested_variables)
            ambiguous = tuple(
                mention for mention in ambiguous
                if not explicit_variables.intersection(mention.candidate_variables)
            )
            requested_modalities = tuple(sorted(
                set(self.modality_registry.canonicalize(earth_query.requested_modalities))
                | set(self.modality_registry.for_variables(earth_query.requested_variables))
            ))
            candidate_explicit_modalities = set(
                self.modality_registry.canonicalize(earth_query.requested_modalities)
            )
            # A structured query is authoritative over inferred prose annotations.
            phenomenon_modalities = set()
            base_query = earth_query
            explicit_scope = bool(
                earth_query.point or earth_query.bbox or earth_query.geometry or earth_query.region
            )
            if earth_query.point:
                geographic = (GeographicMention(
                    source_text="structured EarthQuery point", start=0, end=1,
                    resolution="explicit_coordinates", longitude=earth_query.point[0],
                    latitude=earth_query.point[1],
                ),)
            elif earth_query.bbox:
                geographic = (GeographicMention(
                    source_text="structured EarthQuery bbox", start=0, end=1,
                    resolution="explicit_bbox", bbox=earth_query.bbox,
                ),)
            elif earth_query.geometry:
                geographic = (GeographicMention(
                    source_text="structured EarthQuery geometry", start=0, end=1,
                    resolution="explicit_geometry", geometry=earth_query.geometry,
                ),)
            elif earth_query.region:
                geographic = (GeographicMention(
                    source_text="structured EarthQuery region", start=0, end=1,
                    resolution="declared_region", region=earth_query.region,
                ),)
            if earth_query.temporal_start or earth_query.temporal_end:
                temporal = TimeInterpretation(
                    source_text="structured EarthQuery",
                    resolution="explicit",
                    start=earth_query.temporal_start,
                    end=earth_query.temporal_end,
                    reference_time=reference_time,
                    interpretation="Used exactly as supplied by the structured query.",
                )
            if explicit_scope:
                geography_missing = False
        else:
            requested_variables = resolved_variables
            candidate_explicit_modalities = set(modalities)
            base_query = _query_from_extractions(
                variables=requested_variables,
                modalities=requested_modalities,
                spatial_values=spatial_values,
                temporal=temporal,
                global_scope=_has_global_scope(question),
            )
            explicit_scope = bool(
                spatial_values.get("point")
                or spatial_values.get("bbox")
                or spatial_values.get("region")
                or _has_global_scope(question)
            )

        missing = []
        if not requested_variables and not requested_modalities:
            missing.append(
                MissingInformation(
                    field="observation_target",
                    question="What Earth variable, phenomenon, or sensing domain should SatQuery observe?",
                    reason="No unambiguous ontology variable or modality was identified.",
                )
            )
        for mention in ambiguous:
            missing.append(
                MissingInformation(
                    field="variable_interpretation",
                    question=f"Which meaning of {mention.source_text!r} do you intend?",
                    reason="The Earth variable ontology maps this expression to multiple variables.",
                    candidate_values=mention.candidate_variables,
                )
            )
        if geography_missing and not explicit_scope:
            missing.append(
                MissingInformation(
                    field="spatial_scope",
                    question="Which area should the investigation cover? Provide coordinates, a GeoJSON geometry, a supported region, or state that the scope is global.",
                    reason="No spatial scope was resolved from the request or structured query.",
                    candidate_values=tuple(
                        item.source_text
                        for item in geographic
                        if item.resolution == "unresolved"
                    ),
                )
            )
        if temporal.resolution in {"missing", "ambiguous"}:
            missing.append(
                MissingInformation(
                    field="temporal_scope",
                    question="What observation period should be used? Provide dates or an unambiguous relative period such as 'last 7 days'.",
                    reason=(
                        "The request contains a vague temporal expression."
                        if temporal.resolution == "ambiguous"
                        else "No observation period was specified."
                    ),
                )
            )

        requirements = _evidence_requirements(
            requested_variables, requested_modalities, explicit_scope, temporal
        )
        candidates = self._candidate_plans(
            base_query=base_query,
            requested_variables=requested_variables,
            requested_modalities=requested_modalities,
            ambiguous=ambiguous,
            explicit_modalities=candidate_explicit_modalities,
            phenomenon_modalities=phenomenon_modalities,
            matrix=matrix,
            parent_plan_id=plan_id,
        )
        if not candidates and not missing:
            missing.append(
                MissingInformation(
                    field="capability",
                    question="Would you like to revise the observation target or scope?",
                    reason="No registered sensing implementation matches the extracted request.",
                )
            )

        if missing:
            status = "needs_clarification"
        elif not candidates or not any(
            candidate.selected_implementations
            and not candidate.perception_plan.unavailable_variables
            and not candidate.perception_plan.unavailable_modalities
            for candidate in candidates
        ):
            status = "no_capability"
        else:
            status = "ready"

        assumptions = (temporal_assumption,) if temporal_assumption else ()
        capability_snapshot = matrix.capability_snapshot()
        return InvestigationPlan(
            plan_id=plan_id,
            question=question,
            objective=objective,
            hypotheses=hypotheses,
            geographic_entities=geographic,
            time_interpretation=temporal,
            variables=variables,
            phenomena=phenomena,
            requested_modalities=requested_modalities,
            required_evidence=requirements,
            candidate_plans=candidates,
            missing_information=tuple(missing),
            assumptions=assumptions,
            status=status,
            selected_candidate_plan_id=(
                candidates[0].candidate_plan_id if status == "ready" and len(candidates) == 1 else None
            ),
            capability_matrix_revision=matrix.revision,
            capability_snapshot=capability_snapshot,
            reproducibility={
                "planner_id": PLANNER_ID,
                "planner_version": PLANNER_VERSION,
                "request_sha256": request_digest,
                "reference_time": reference_time.isoformat(),
                "time_zone": "UTC",
                "ontology_sha256": ontology_revision,
                "capability_matrix_revision": matrix.revision,
                "capability_snapshot_sha256": capability_snapshot.snapshot_sha256,
                "rules": [
                    "exact-ontology-alias-match",
                    "explicit-coordinate-and-declared-region-resolution",
                    "explicit-or-defined-relative-time-interpretation",
                    "capability-matrix-filtering",
                ],
            },
            limitations=(
                "Planning is deterministic lexical and metadata-based; it does not establish scientific truth.",
                "No connector is invoked and no observation is acquired while producing this plan.",
                "Named places without an exact declared-region match require a gazetteer or user-supplied geometry.",
            ),
        )

    def _candidate_plans(
        self,
        *,
        base_query: EarthQuery,
        requested_variables: tuple[str, ...],
        requested_modalities: tuple[str, ...],
        ambiguous: tuple[VariableMention, ...],
        explicit_modalities: set[str],
        phenomenon_modalities: set[str],
        matrix: EarthCapabilityMatrix,
        parent_plan_id: str,
    ) -> tuple[CandidateInvestigationPlan, ...]:
        interpretations: list[tuple[tuple[str, ...], str]] = []
        if ambiguous:
            choices = [item.candidate_variables for item in ambiguous]
            for combination in itertools.islice(
                itertools.product(*choices), self.max_candidate_plans
            ):
                variables = tuple(sorted(set((*requested_variables, *combination))))
                label = "; ".join(
                    f"{mention.source_text} → {variable}"
                    for mention, variable in zip(ambiguous, combination)
                )
                interpretations.append((variables, label))
        else:
            interpretations.append((tuple(sorted(set(requested_variables))), "Ontology and explicit scope interpretation"))

        candidates = []
        for variables, interpretation in interpretations:
            candidate_modalities = tuple(sorted(
                explicit_modalities
                | phenomenon_modalities
                | set(self.modality_registry.for_variables(variables))
            ))
            query = base_query.model_copy(update={
                "requested_variables": variables,
                "requested_modalities": candidate_modalities,
            })
            try:
                capability_plan = self.capability_plan(query)
            except (ValueError, ValidationError):
                continue
            selected_ids = set(capability_plan.implementation_ids)
            entries = [
                entry for entry in matrix.entries
                if entry.scope == "dataset" and entry.connector_id in selected_ids
                and entry.dataset_reference is not None
                and (
                    not capability_plan.dataset_ids
                    or entry.dataset_reference.dataset_id in capability_plan.dataset_ids
                )
            ]
            references = tuple(
                sorted(
                    {entry.dataset_reference for entry in entries if entry.dataset_reference is not None},
                    key=lambda item: (item.connector_id, item.dataset_id, item.version or ""),
                )
            )
            qualities = tuple(
                ObservationQualityExpectation(
                    dataset_id=entry.dataset_id or "unknown",
                    declared_quality=entry.quality_metadata,
                    declared_uncertainty=entry.uncertainty_metadata,
                    confidence_available=entry.confidence_available,
                    basis="dataset_declaration" if entry.quality_metadata or entry.uncertainty_metadata else "unknown",
                )
                for entry in entries if entry.dataset_id is not None
            )
            cost = _declared_cost(entries)
            provider_assessments = _provider_assessments(matrix, selected_ids)
            steps = _make_steps(
                query=query,
                variables=variables,
                modalities=candidate_modalities,
                capability_plan=capability_plan,
                entries=entries,
                references=references,
                qualities=qualities,
                cost=cost,
                provider_assessments=provider_assessments,
                modality_registry=self.modality_registry,
                capability_plan_fn=self.capability_plan,
            )
            candidates.append(
                CandidateInvestigationPlan(
                    candidate_plan_id=_stable_identifier(
                        f"{parent_plan_id}:{','.join(variables)}:{interpretation}"
                    ),
                    interpretation=interpretation,
                    selected_variables=variables,
                    earth_query=query,
                    perception_plan=capability_plan,
                    selected_datasets=references,
                    selected_implementations=capability_plan.implementation_ids,
                    provider_assessments=provider_assessments,
                    quality_expectations=qualities,
                    cost_estimate=cost,
                    steps=steps,
                )
            )
        return tuple(candidates)


def _extract_objective(text: str) -> Optional[ObjectiveExtraction]:
    patterns = (
        ("compare", r"\b(compare|change|difference|trend)\b"),
        ("monitor", r"\b(monitor|track|watch)\b"),
        ("detect", r"\b(detect|identify|find|locate)\b"),
        ("map", r"\b(map|mapping|delineate)\b"),
        ("measure", r"\b(measure|estimate|quantify)\b"),
        ("assess", r"\b(assess|evaluate|characterize)\b"),
        ("observe", r"\b(observe|show|what is|where is|how much|how many)\b"),
    )
    lowered = text.casefold()
    for objective_type, pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            source = text[match.start():match.end()]
            return ObjectiveExtraction(
                objective_type=objective_type,
                statement=text.strip(),
                source_text=source,
                start=match.start(),
                end=match.end(),
            )
    return None


def _extract_hypotheses(text: str) -> tuple[CandidateHypothesis, ...]:
    explicit = re.search(r"\bhypothesis\s*:\s*([^.;\n]+)", text, re.IGNORECASE)
    if explicit:
        statement = explicit.group(1).strip()
        return (CandidateHypothesis(statement=statement, source_text=explicit.group(0), origin="explicit"),)
    derived = re.search(r"\b(?:test whether|determine whether|is there|did)\s+([^?]+)", text, re.IGNORECASE)
    if derived:
        claim = derived.group(1).strip().rstrip(".")
        return (CandidateHypothesis(
            statement=f"Question-derived proposition to evaluate: {claim}",
            source_text=derived.group(0),
            origin="question_derived",
        ),)
    return ()


def _extract_variables(text: str, ontology: EarthVariableOntology) -> tuple[VariableMention, ...]:
    matches: dict[tuple[int, int], set[str]] = {}
    for variable in ontology.variables:
        for alias in (variable.canonical_name, variable.canonical_name.replace("_", " "), *variable.aliases):
            phrase = alias.strip()
            if not phrase:
                continue
            for match in re.finditer(rf"(?<![\w]){re.escape(phrase)}(?![\w])", text, re.IGNORECASE):
                matches.setdefault((match.start(), match.end()), set()).add(variable.canonical_name)
    selected = []
    occupied: list[tuple[int, int]] = []
    for (start, end), canonical_names in sorted(
        matches.items(), key=lambda item: (-(item[0][1] - item[0][0]), item[0][0], item[0][1])
    ):
        if any(start < prior_end and prior_start < end for prior_start, prior_end in occupied):
            continue
        occupied.append((start, end))
        candidates = tuple(sorted(canonical_names))
        resolved = candidates[0] if len(candidates) == 1 else None
        variable = ontology.variable(resolved) if resolved else None
        selected.append(VariableMention(
            source_text=text[start:end], start=start, end=end,
            canonical_variable=resolved, candidate_variables=candidates,
            ontology_concept_id=variable.concept_id if variable else None,
            ontology_uri=variable.ontology_uri if variable else None,
            resolution="resolved" if resolved else "ambiguous",
        ))
    return tuple(sorted(selected, key=lambda item: (item.start, item.end)))


def _extract_phenomena(text: str, ontology: EarthVariableOntology) -> tuple[PhenomenonMention, ...]:
    found: dict[tuple[int, int, str], PhenomenonMention] = {}
    for concept in ontology.concepts:
        for alias in (concept.label, concept.concept_id, *concept.aliases):
            if not alias.strip():
                continue
            for match in re.finditer(rf"(?<![\w]){re.escape(alias)}(?![\w])", text, re.IGNORECASE):
                item = PhenomenonMention(
                    source_text=text[match.start():match.end()], concept_id=concept.concept_id,
                    label=concept.label, start=match.start(), end=match.end(),
                )
                found[(match.start(), match.end(), concept.concept_id)] = item
    return tuple(found[key] for key in sorted(found))


def _extract_modalities(text: str, registry: SensingModalityRegistry) -> tuple[str, ...]:
    lowered = text.casefold()
    requested = set()
    for modality in registry.modalities():
        for alias in (modality.modality_id, modality.label, *modality.aliases):
            if re.search(rf"(?<![\w]){re.escape(alias.casefold())}(?![\w])", lowered):
                requested.add(modality.modality_id)
    return tuple(sorted(requested))


def _extract_geography(
    text: str, matrix: EarthCapabilityMatrix
) -> tuple[tuple[GeographicMention, ...], dict[str, Any], bool]:
    longitude = re.search(r"\b(?:lon|longitude)\s*[:=]\s*(-?\d+(?:\.\d+)?)", text, re.IGNORECASE)
    latitude = re.search(r"\b(?:lat|latitude)\s*[:=]\s*(-?\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if longitude and latitude:
        lon, lat = float(longitude.group(1)), float(latitude.group(1))
        start, end = min(longitude.start(), latitude.start()), max(longitude.end(), latitude.end())
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            mention = GeographicMention(
                source_text=text[start:end], start=start, end=end, resolution="unresolved"
            )
            return (mention,), {}, True
        mention = GeographicMention(
            source_text=text[start:end], start=start, end=end,
            resolution="explicit_coordinates", longitude=lon, latitude=lat,
        )
        return (mention,), {"point": (lon, lat)}, False

    bbox = re.search(
        r"\bbbox\s*[:=]?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)",
        text, re.IGNORECASE,
    )
    if bbox:
        values = tuple(float(bbox.group(index)) for index in range(1, 5))
        if not (-180 <= values[0] <= 180 and -90 <= values[1] <= 90
                and -180 <= values[2] <= 180 and -90 <= values[3] <= 90
                and values[0] <= values[2] and values[1] <= values[3]):
            mention = GeographicMention(
                source_text=bbox.group(0), start=bbox.start(), end=bbox.end(),
                resolution="unresolved",
            )
            return (mention,), {}, True
        mention = GeographicMention(
            source_text=bbox.group(0), start=bbox.start(), end=bbox.end(),
            resolution="explicit_bbox", bbox=values,
        )
        return (mention,), {"bbox": values}, False

    declared_regions = sorted({
        region for entry in matrix.entries for region in entry.supported_regions
        if region.strip() and region != "*"
    }, key=lambda value: (-len(value), value.casefold()))
    lowered = text.casefold()
    for region in declared_regions:
        match = re.search(rf"(?<![\w]){re.escape(region.casefold())}(?![\w])", lowered)
        if match:
            mention = GeographicMention(
                source_text=text[match.start():match.end()], start=match.start(), end=match.end(),
                resolution="declared_region", region=region,
            )
            return (mention,), {"region": region}, False

    name_match = re.search(
        r"\b(?:in|near|around|over|across|within)\s+([A-Z][\w'-]*(?:\s+(?:[A-Z][\w'-]*|of|the|de)){0,3})",
        text,
    )
    if name_match:
        start, end = name_match.start(1), name_match.end(1)
        mention = GeographicMention(
            source_text=text[start:end], start=start, end=end, resolution="unresolved"
        )
        return (mention,), {}, True
    return (), {}, True


def _extract_time(
    text: str, reference_time: datetime
) -> tuple[TimeInterpretation, Optional[PlannerAssumption]]:
    reference_time = reference_time.astimezone(timezone.utc)
    range_match = re.search(
        r"\b(?:between|from)\s+(\d{4}-\d{2}-\d{2})\s+(?:and|to|through|until)\s+(\d{4}-\d{2}-\d{2})\b",
        text, re.IGNORECASE,
    )
    if range_match:
        try:
            start_date = date.fromisoformat(range_match.group(1))
            end_date = date.fromisoformat(range_match.group(2))
        except ValueError:
            return _ambiguous_time(range_match.group(0), reference_time), None
        if start_date > end_date:
            return _ambiguous_time(range_match.group(0), reference_time), None
        start, end = _utc_day(start_date)
        _, end = _utc_day(end_date)
        return TimeInterpretation(
            source_text=range_match.group(0), resolution="explicit", start=start, end=end,
            reference_time=reference_time, interpretation="Inclusive UTC calendar dates.",
        ), _utc_assumption(range_match.group(0))

    relative = re.search(
        r"\b(?:last|past)\s+(\d+)\s+(minutes?|hours?|days?|weeks?)\b",
        text,
        re.IGNORECASE,
    )
    if relative:
        count = int(relative.group(1))
        if count < 1 or count > 36500:
            return _ambiguous_time(relative.group(0), reference_time), None
        unit = relative.group(2).casefold()
        if unit.startswith("minute"):
            delta = timedelta(minutes=count)
        elif unit.startswith("hour"):
            delta = timedelta(hours=count)
        elif unit.startswith("day"):
            delta = timedelta(days=count)
        else:
            delta = timedelta(weeks=count)
        return TimeInterpretation(
            source_text=relative.group(0), resolution="relative", start=reference_time - delta,
            end=reference_time, reference_time=reference_time,
            interpretation="Trailing duration ending at the recorded planner reference time.",
        ), PlannerAssumption(
            field="relative_time_anchor", value=reference_time.isoformat(),
            source="deterministic_interpretation",
            rationale="Relative period is anchored to the recorded UTC planning time.",
        )

    last_month = re.search(r"\blast month\b", text, re.IGNORECASE)
    if last_month:
        first_this_month = datetime(reference_time.year, reference_time.month, 1, tzinfo=timezone.utc)
        previous_end = first_this_month - timedelta(microseconds=1)
        previous_month = first_this_month - timedelta(days=1)
        start = datetime(previous_month.year, previous_month.month, 1, tzinfo=timezone.utc)
        return TimeInterpretation(
            source_text=last_month.group(0), resolution="relative", start=start, end=previous_end,
            reference_time=reference_time,
            interpretation="Previous complete UTC calendar month.",
        ), PlannerAssumption(
            field="calendar_month_semantics", value="previous_complete_UTC_calendar_month",
            source="deterministic_interpretation",
            rationale="'Last month' is interpreted as the previous completed calendar month.",
        )

    last_week = re.search(r"\blast week\b", text, re.IGNORECASE)
    if last_week:
        current_week_start = datetime(
            reference_time.year, reference_time.month, reference_time.day,
            tzinfo=timezone.utc,
        ) - timedelta(days=reference_time.weekday())
        start = current_week_start - timedelta(days=7)
        end = current_week_start - timedelta(microseconds=1)
        return TimeInterpretation(
            source_text=last_week.group(0), resolution="relative", start=start, end=end,
            reference_time=reference_time,
            interpretation="Previous complete ISO week (Monday through Sunday, UTC).",
        ), PlannerAssumption(
            field="calendar_week_semantics", value="previous_complete_ISO_week_UTC",
            source="deterministic_interpretation",
            rationale="'Last week' is interpreted as the previous completed ISO week.",
        )

    last_year = re.search(r"\blast year\b", text, re.IGNORECASE)
    if last_year:
        year = reference_time.year - 1
        return TimeInterpretation(
            source_text=last_year.group(0), resolution="relative",
            start=datetime(year, 1, 1, tzinfo=timezone.utc),
            end=datetime(year, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc),
            reference_time=reference_time,
            interpretation="Previous complete UTC calendar year.",
        ), PlannerAssumption(
            field="calendar_year_semantics", value="previous_complete_UTC_calendar_year",
            source="deterministic_interpretation",
            rationale="'Last year' is interpreted as the previous completed calendar year.",
        )

    this_year = re.search(r"\bthis year\b", text, re.IGNORECASE)
    if this_year:
        return TimeInterpretation(
            source_text=this_year.group(0), resolution="relative",
            start=datetime(reference_time.year, 1, 1, tzinfo=timezone.utc),
            end=reference_time, reference_time=reference_time,
            interpretation="Current UTC calendar year through planner reference time.",
        ), PlannerAssumption(
            field="relative_time_anchor", value=reference_time.isoformat(),
            source="deterministic_interpretation",
            rationale="'This year' is bounded by the recorded planner reference time.",
        )

    this_month = re.search(r"\bthis month\b", text, re.IGNORECASE)
    if this_month:
        return TimeInterpretation(
            source_text=this_month.group(0), resolution="relative",
            start=datetime(reference_time.year, reference_time.month, 1, tzinfo=timezone.utc),
            end=reference_time, reference_time=reference_time,
            interpretation="Current UTC calendar month through planner reference time.",
        ), PlannerAssumption(
            field="relative_time_anchor", value=reference_time.isoformat(),
            source="deterministic_interpretation",
            rationale="'This month' is bounded by the recorded planner reference time.",
        )

    past_month = re.search(r"\bpast month\b", text, re.IGNORECASE)
    if past_month:
        return _ambiguous_time(past_month.group(0), reference_time), None
    past_year = re.search(r"\bpast year\b", text, re.IGNORECASE)
    if past_year:
        return _ambiguous_time(past_year.group(0), reference_time), None

    today = re.search(r"\btoday\b", text, re.IGNORECASE)
    if today:
        start, end = _utc_day(reference_time.date())
        return TimeInterpretation(
            source_text=today.group(0), resolution="relative", start=start, end=end,
            reference_time=reference_time,
            interpretation="Current UTC calendar day.",
        ), PlannerAssumption(
            field="calendar_day_semantics", value="current_UTC_calendar_day",
            source="deterministic_interpretation",
            rationale="'Today' is evaluated against the recorded planner reference time in UTC.",
        )

    if re.search(r"\b(?:now|current|currently|latest|recent|recently)\b", text, re.IGNORECASE):
        current = re.search(r"\b(?:now|current|currently)\b", text, re.IGNORECASE)
        if current:
            return TimeInterpretation(
                source_text=current.group(0), resolution="relative", start=reference_time,
                end=reference_time, reference_time=reference_time,
                interpretation="Instantaneous request anchored to planner reference time; source latency may differ.",
            ), PlannerAssumption(
                field="relative_time_anchor", value=reference_time.isoformat(),
                source="deterministic_interpretation",
                rationale="The request explicitly refers to the current instant.",
            )
        vague = re.search(r"\b(?:latest|recent|recently)\b", text, re.IGNORECASE)
        return _ambiguous_time(vague.group(0) if vague else "", reference_time), None

    year_month = re.search(r"\b(?:during\s+)?(\d{4})-(\d{2})\b", text)
    if year_month:
        year, month = int(year_month.group(1)), int(year_month.group(2))
        if month < 1 or month > 12:
            return _ambiguous_time(year_month.group(0), reference_time), None
        try:
            last_day = monthrange(year, month)[1]
            start = datetime(year, month, 1, tzinfo=timezone.utc)
            end = datetime(year, month, last_day, 23, 59, 59, 999999, tzinfo=timezone.utc)
        except ValueError:
            return _ambiguous_time(year_month.group(0), reference_time), None
        return TimeInterpretation(
            source_text=year_month.group(0), resolution="explicit", start=start, end=end,
            reference_time=reference_time, interpretation="Inclusive UTC calendar month.",
        ), _utc_assumption(year_month.group(0))

    month_names = {
        name.casefold(): index for index, name in enumerate(
            ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
            start=1,
        )
    }
    month_pattern = "|".join((*month_names.keys(), *(name[:3] for name in month_names)))
    named_month = re.search(rf"\b({month_pattern})\s+(\d{{4}})\b", text, re.IGNORECASE)
    if named_month:
        month_token, year = named_month.group(1).casefold(), int(named_month.group(2))
        month = month_names.get(month_token, month_names.get(month_token[:3]))
        try:
            last_day = monthrange(year, month)[1]
            start = datetime(year, month, 1, tzinfo=timezone.utc)
            end = datetime(year, month, last_day, 23, 59, 59, 999999, tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return _ambiguous_time(named_month.group(0), reference_time), None
        return TimeInterpretation(
            source_text=named_month.group(0), resolution="explicit", start=start, end=end,
            reference_time=reference_time, interpretation="Inclusive UTC calendar month.",
        ), _utc_assumption(named_month.group(0))

    year_match = re.search(r"\b(?:during|in|year)\s+(\d{4})\b", text, re.IGNORECASE)
    if year_match:
        year = int(year_match.group(1))
        if year < 1:
            return _ambiguous_time(year_match.group(0), reference_time), None
        return TimeInterpretation(
            source_text=year_match.group(0), resolution="explicit",
            start=datetime(year, 1, 1, tzinfo=timezone.utc),
            end=datetime(year, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc),
            reference_time=reference_time, interpretation="Inclusive UTC calendar year.",
        ), _utc_assumption(year_match.group(0))

    timestamp_match = re.search(
        r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})\b",
        text,
        re.IGNORECASE,
    )
    if timestamp_match:
        raw_timestamp = timestamp_match.group(0)
        try:
            value = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00").replace("z", "+00:00"))
        except ValueError:
            return _ambiguous_time(raw_timestamp, reference_time), None
        if value.tzinfo is None:
            return _ambiguous_time(raw_timestamp, reference_time), None
        value = value.astimezone(timezone.utc)
        return TimeInterpretation(
            source_text=raw_timestamp, resolution="explicit", start=value, end=value,
            reference_time=reference_time, interpretation="Exact instant normalized to UTC.",
        ), None

    date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if date_match:
        try:
            start, end = _utc_day(date.fromisoformat(date_match.group(1)))
        except ValueError:
            return _ambiguous_time(date_match.group(1), reference_time), None
        return TimeInterpretation(
            source_text=date_match.group(1), resolution="explicit", start=start, end=end,
            reference_time=reference_time, interpretation="Inclusive UTC calendar day.",
        ), _utc_assumption(date_match.group(1))

    return TimeInterpretation(
        resolution="missing", reference_time=reference_time,
        interpretation="No temporal scope was extracted.",
    ), None


def _ambiguous_time(source: str, reference_time: datetime) -> TimeInterpretation:
    return TimeInterpretation(
        source_text=source or None, resolution="ambiguous", reference_time=reference_time,
        interpretation="The phrase does not define a reproducible time interval.",
    )


def _utc_day(value: date) -> tuple[datetime, datetime]:
    start = datetime.combine(value, time.min, tzinfo=timezone.utc)
    end = datetime.combine(value, time.max, tzinfo=timezone.utc)
    return start, end


def _utc_assumption(source: str) -> PlannerAssumption:
    return PlannerAssumption(
        field="timezone", value="UTC", source="deterministic_interpretation",
        rationale=f"Date-only expression {source!r} is interpreted as an inclusive UTC calendar interval.",
    )


def _query_from_extractions(
    *, variables: tuple[str, ...], modalities: tuple[str, ...],
    spatial_values: dict[str, Any], temporal: TimeInterpretation, global_scope: bool = False,
) -> EarthQuery:
    values: dict[str, Any] = {
        "requested_variables": variables,
        "requested_modalities": modalities,
        **spatial_values,
    }
    if global_scope and not spatial_values:
        values["region"] = "*"
    if temporal.resolution in {"explicit", "relative"}:
        values["temporal_start"] = temporal.start
        values["temporal_end"] = temporal.end
    return EarthQuery(**values)


def _has_global_scope(text: str) -> bool:
    return bool(re.search(r"\b(global|globally|worldwide|planet[- ]wide|entire earth)\b", text, re.IGNORECASE))


def _evidence_requirements(
    variables: tuple[str, ...], modalities: tuple[str, ...],
    spatial_present: bool, temporal: TimeInterpretation,
) -> tuple[EvidenceRequirement, ...]:
    requirements = [
        EvidenceRequirement(
            requirement_id=f"variable:{variable}", evidence_type="variable", target=variable,
            rationale="Requested measurement extracted from the Earth variable ontology.",
        ) for variable in variables
    ]
    requirements.extend(
        EvidenceRequirement(
            requirement_id=f"modality:{modality}", evidence_type="modality", target=modality,
            rationale="Requested sensing domain was explicit or ontology-resolved.",
        ) for modality in modalities
    )
    requirements.append(EvidenceRequirement(
        requirement_id="spatial_scope", evidence_type="spatial_scope",
        target="specified Earth area" if spatial_present else "Earth area",
        rationale=(
            "The specified spatial scope constrains observation selection."
            if spatial_present
            else "Spatial scope is needed to constrain observation selection."
        ),
    ))
    temporal_present = temporal.resolution in {"explicit", "relative"}
    requirements.append(EvidenceRequirement(
        requirement_id="temporal_scope", evidence_type="temporal_scope",
        target="specified observation period" if temporal_present else "observation period",
        rationale=(
            "The specified time interval constrains observation selection."
            if temporal_present
            else "Temporal scope is needed to select reproducible observation records."
        ),
    ))
    return tuple(requirements)


def _declared_cost(entries) -> DeclaredCostEstimate:
    values = []
    for entry in entries:
        policy = entry.access_policy
        amount = policy.get("cost_per_query", policy.get("cost"))
        currency = policy.get("currency")
        unit = policy.get("pricing_unit", "query") if amount is not None else None
        if isinstance(amount, (int, float)) and not isinstance(amount, bool) and amount >= 0 and currency:
            values.append((float(amount), str(currency), str(unit), entry.dataset_id or "unknown"))
    if entries and len(values) == len(entries) and len({(currency, unit) for _, currency, unit, _ in values}) == 1:
        return DeclaredCostEstimate(
            status="declared", amount=sum(value for value, _, _, _ in values),
            currency=values[0][1], pricing_unit=values[0][2],
            source_dataset_ids=tuple(sorted(item[3] for item in values)),
            explanation="Computed only from explicit dataset access-policy pricing fields.",
        )
    return DeclaredCostEstimate(
        status="unknown", source_dataset_ids=tuple(sorted(entry.dataset_id for entry in entries if entry.dataset_id)),
        explanation="No complete, compatible declared price is available; no cost was inferred.",
    )


def _make_steps(
    *, query: EarthQuery, variables: tuple[str, ...], modalities: tuple[str, ...],
    capability_plan: PerceptionPlan, entries, references, qualities, cost,
    capability_plan_fn: Callable[[EarthQuery], PerceptionPlan],
    provider_assessments: tuple[ProviderAssessment, ...],
    modality_registry: SensingModalityRegistry,
) -> tuple[PlannedObservationStep, ...]:
    groups: dict[str, set[str]] = {}
    for modality in modalities:
        groups.setdefault(modality, set())
    for variable in variables:
        mapped = sorted(set(modality_registry.for_variable(variable)) & set(modalities))
        if mapped:
            for modality in mapped:
                groups.setdefault(modality, set()).add(variable)
        else:
            groups.setdefault("cross-domain", set()).add(variable)
    if not groups and (variables or modalities):
        groups["cross-domain"] = set(variables)
    steps = []
    for modality, group_variables in sorted(groups.items()):
        step_modalities = () if modality == "cross-domain" else (modality,)
        step_query = query.model_copy(update={
            "requested_modalities": step_modalities,
            "requested_variables": tuple(sorted(group_variables)),
        })
        step_plan = capability_plan_fn(step_query)
        step_ids = set(step_plan.implementation_ids)
        step_entries = tuple(entry for entry in entries if entry.connector_id in step_ids)
        step_datasets = tuple(ref for ref in references if ref.connector_id in step_ids)
        step_quality = tuple(item for item in qualities if item.dataset_id in {ref.dataset_id for ref in step_datasets})
        step_cost = _declared_cost(step_entries)
        steps.append(PlannedObservationStep(
            step_id=f"observe:{modality}",
            description=(f"Acquire {', '.join(sorted(group_variables))}" if group_variables else f"Acquire {modality} observations"),
            requested_modalities=step_modalities,
            requested_variables=tuple(sorted(group_variables)),
            earth_query=step_query,
            perception_plan=step_plan,
            selected_datasets=step_datasets,
            selected_implementations=step_plan.implementation_ids,
            provider_assessments=tuple(
                item for item in provider_assessments if item.connector_id in step_ids
            ),
            quality_expectations=step_quality,
            cost_estimate=step_cost,
        ))
    return tuple(steps)


def _provider_assessments(
    matrix: EarthCapabilityMatrix, selected_ids: set[str]
) -> tuple[ProviderAssessment, ...]:
    entries = {}
    for entry in matrix.entries:
        if entry.connector_id in selected_ids:
            entries.setdefault(entry.connector_id, entry)
    return tuple(
        ProviderAssessment(
            connector_id=entry.connector_id,
            provider=entry.provider,
            provider_version=entry.provider_version,
            registered=entry.connector_registered,
            declared_available=entry.connector_available,
            declared_health=entry.connector_health,
        )
        for _, entry in sorted(entries.items())
    )


def _ontology_revision(ontology: EarthVariableOntology) -> str:
    payload = {
        "concepts": [
            (item.concept_id, item.label, item.parent_id, item.aliases, item.related_concepts)
            for item in ontology.concepts
        ],
        "variables": [
            (item.canonical_name, item.concept_id, item.label, item.aliases, item.ontology_uri)
            for item in ontology.variables
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stable_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
