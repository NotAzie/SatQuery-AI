"""Auditable validation, certification, plugin trust, and investigation export.

This module defines governance contracts only. It contains no benchmark data or
scientific reference outputs. Certification requires executing caller-supplied
reference cases and recording independent review artifacts where applicable.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime
from typing import Any, Iterable, Literal, Protocol

from pydantic import Field, model_validator

from .contracts import Contract, utc_now


def canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=str, allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def reproducibility_report_digest(report: "ReproducibilityReport") -> str:
    return canonical_digest(report.model_dump(
        mode="json", exclude={"report_sha256", "report_id", "executed_at"}
    ))


class ValidationDatasetManifest(Contract):
    dataset_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    uri: str = Field(min_length=1)
    license: str = Field(min_length=1)
    provenance: dict[str, Any]
    partition: Literal["development", "validation", "test", "reference"]
    access_constraints: tuple[str, ...] = ()


class BenchmarkCase(Contract):
    case_id: str = Field(min_length=1)
    reference_investigation_id: str = Field(min_length=1)
    input_manifest: dict[str, Any]
    input_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    expected_output: dict[str, Any]
    expected_output_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    validation_dataset_ids: tuple[str, ...] = Field(min_length=1)
    reference_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def verify_declared_digests(self) -> "BenchmarkCase":
        if canonical_digest(self.input_manifest) != self.input_sha256:
            raise ValueError("benchmark input digest does not match its manifest")
        if canonical_digest(self.expected_output) != self.expected_output_sha256:
            raise ValueError("benchmark expected-output digest does not match its payload")
        return self


class ReferenceInvestigation(Contract):
    reference_investigation_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    reproducibility_bundle_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    provenance: dict[str, Any]
    scientific_reference_ids: tuple[str, ...] = Field(min_length=1)
    benchmark_case_ids: tuple[str, ...] = Field(min_length=1)


class ScientificBenchmarkSuite(Contract):
    suite_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    method_id: str = Field(min_length=1)
    method_version: str = Field(min_length=1)
    domain: Literal["hydrology", "wildfire", "flooding", "land_cover", "climate", "vegetation", "disaster_monitoring"]
    validation_datasets: tuple[ValidationDatasetManifest, ...] = Field(min_length=1)
    reference_investigations: tuple[ReferenceInvestigation, ...] = Field(min_length=1)
    cases: tuple[BenchmarkCase, ...] = Field(min_length=1)
    suite_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    scientific_references: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def check_case_ids(self) -> "ScientificBenchmarkSuite":
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("benchmark case IDs must be unique")
        if canonical_digest(self.model_dump(mode="json", exclude={"suite_sha256"})) != self.suite_sha256:
            raise ValueError("benchmark suite digest does not match its declared datasets and cases")
        dataset_ids = {item.dataset_id for item in self.validation_datasets}
        if len(dataset_ids) != len(self.validation_datasets):
            raise ValueError("validation dataset identifiers must be unique in a suite")
        if any(not set(case.validation_dataset_ids).issubset(dataset_ids) for case in self.cases):
            raise ValueError("benchmark case references datasets absent from the suite")
        references = {item.reference_investigation_id for item in self.reference_investigations}
        if len(references) != len(self.reference_investigations):
            raise ValueError("reference investigation IDs must be unique in a suite")
        if any(case.reference_investigation_id not in references for case in self.cases):
            raise ValueError("benchmark case references an investigation absent from the suite")
        case_ids = {item.case_id for item in self.cases}
        if any(not set(item.benchmark_case_ids).issubset(case_ids) for item in self.reference_investigations):
            raise ValueError("reference investigation case links must resolve within the suite")
        return self


class BenchmarkCaseResult(Contract):
    case_id: str
    status: Literal["passed", "failed", "error"]
    actual_output_sha256: str | None = None
    expected_output_sha256: str
    explanation: str


class ReproducibilityReport(Contract):
    report_id: str
    suite_id: str
    suite_version: str
    method_id: str
    method_version: str
    implementation_sha256: str
    status: Literal["passed", "failed", "incomplete"]
    case_results: tuple[BenchmarkCaseResult, ...]
    input_manifest_sha256: str
    execution_environment: dict[str, str]
    executed_at: datetime = Field(default_factory=utc_now)
    runner_id: str
    report_sha256: str

    @model_validator(mode="after")
    def report_digest_matches(self) -> "ReproducibilityReport":
        if self.report_sha256 != "0" * 64 and self.report_sha256 != reproducibility_report_digest(self):
            raise ValueError("reproducibility report digest does not match its contents")
        return self


class ScientificMethodRunner(Protocol):
    runner_id: str
    implementation_sha256: str

    def execute(self, case: BenchmarkCase, datasets: dict[str, bytes]) -> dict[str, Any]: ...


class ValidationDatasetLoader(Protocol):
    def load(self, manifest: ValidationDatasetManifest) -> bytes: ...


class ScientificValidationExecutor:
    """Run supplied reference cases and compare canonical outputs exactly."""

    def execute(
        self,
        suite: ScientificBenchmarkSuite,
        *,
        implementation_sha256: str,
        runner: ScientificMethodRunner,
        dataset_loader: ValidationDatasetLoader,
        execution_environment: dict[str, str],
    ) -> ReproducibilityReport:
        if runner.implementation_sha256 != implementation_sha256:
            raise ValueError("runner implementation digest does not match the registered method digest")
        results: list[BenchmarkCaseResult] = []
        datasets_by_id = {item.dataset_id: item for item in suite.validation_datasets}
        for case in suite.cases:
            try:
                dataset_bytes = {
                    dataset_id: dataset_loader.load(datasets_by_id[dataset_id])
                    for dataset_id in case.validation_dataset_ids
                }
                for dataset_id, content in dataset_bytes.items():
                    expected_digest = datasets_by_id[dataset_id].content_sha256.casefold()
                    actual_digest = hashlib.sha256(content).hexdigest()
                    if actual_digest != expected_digest:
                        raise ValueError("validation dataset content digest mismatch")
            except Exception as exc:
                results.append(BenchmarkCaseResult(
                    case_id=case.case_id, status="error",
                    expected_output_sha256=case.expected_output_sha256,
                    explanation=f"Validation dataset loading or integrity check failed with {type(exc).__name__}.",
                ))
                continue
            try:
                actual = runner.execute(case, dataset_bytes)
                digest = canonical_digest(actual)
                expected = canonical_digest(case.expected_output)
                passed = digest == expected
                results.append(BenchmarkCaseResult(
                    case_id=case.case_id,
                    status="passed" if passed else "failed",
                    actual_output_sha256=digest,
                    expected_output_sha256=expected,
                    explanation="Canonical output exactly matches the declared reference." if passed else "Canonical output differs from the declared reference; no tolerance was assumed.",
                ))
            except Exception as exc:
                results.append(BenchmarkCaseResult(
                    case_id=case.case_id, status="error",
                    expected_output_sha256=case.expected_output_sha256,
                    explanation=f"Runner raised {type(exc).__name__}; raw exception data was omitted.",
                ))
        status = "passed" if all(item.status == "passed" for item in results) else "failed"
        input_hash = canonical_digest({
            "suite": suite.model_dump(mode="json"),
            "implementation_sha256": implementation_sha256,
            "environment": execution_environment,
        })
        provisional = ReproducibilityReport(
            report_id=uuid.uuid4().hex,
            suite_id=suite.suite_id,
            suite_version=suite.version,
            method_id=suite.method_id,
            method_version=suite.method_version,
            implementation_sha256=implementation_sha256,
            status=status,
            case_results=tuple(results),
            input_manifest_sha256=input_hash,
            execution_environment=execution_environment,
            runner_id=runner.runner_id,
            report_sha256="0" * 64,
        )
        return provisional.model_copy(update={"report_sha256": reproducibility_report_digest(provisional)})


CertificationState = Literal[
    "experimental", "internal", "peer_reviewed", "reference_implementation",
    "deprecated", "retired",
]


class PeerReviewArtifact(Contract):
    review_id: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    decision: Literal["accepted", "rejected", "conditional"]
    reference_uri: str = Field(min_length=1)
    reviewed_at: datetime = Field(default_factory=utc_now)
    comments_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class MethodCertificationEvent(Contract):
    event_id: str
    method_id: str
    method_version: str
    version: int = Field(ge=1)
    prior_state: CertificationState | None = None
    state: CertificationState
    actor: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    benchmark_report_ids: tuple[str, ...] = ()
    peer_review: PeerReviewArtifact | None = None
    occurred_at: datetime = Field(default_factory=utc_now)


class ScientificMethodCertificationLedger:
    """Append-only lifecycle ledger with evidence-gated certification transitions."""

    _TRANSITIONS = {
        "experimental": {"internal", "deprecated", "retired"},
        "internal": {"peer_reviewed", "reference_implementation", "deprecated", "retired"},
        "peer_reviewed": {"reference_implementation", "deprecated", "retired"},
        "reference_implementation": {"deprecated", "retired"},
        "deprecated": {"internal", "retired"},
        "retired": set(),
    }

    def __init__(self) -> None:
        self._events: dict[tuple[str, str], list[MethodCertificationEvent]] = {}
        self._reports: dict[str, ReproducibilityReport] = {}
        self._lock = threading.RLock()

    def _store_report(self, report: ReproducibilityReport) -> None:
        with self._lock:
            if report.report_id in self._reports:
                raise ValueError("reproducibility report ID already recorded")
            expected_digest = reproducibility_report_digest(report)
            if report.report_sha256 != expected_digest:
                raise ValueError("reproducibility report digest is invalid")
            self._reports[report.report_id] = report

    def execute_benchmark(
        self, suite: ScientificBenchmarkSuite, *, implementation_sha256: str,
        runner: ScientificMethodRunner, dataset_loader: ValidationDatasetLoader,
        execution_environment: dict[str, str],
    ) -> ReproducibilityReport:
        report = ScientificValidationExecutor().execute(
            suite, implementation_sha256=implementation_sha256,
            runner=runner, dataset_loader=dataset_loader,
            execution_environment=execution_environment,
        )
        self._store_report(report)
        return report

    def register(self, method_id: str, method_version: str, *, actor: str = "satquery.registry", rationale: str = "Method version entered the experimental catalog.") -> MethodCertificationEvent:
        with self._lock:
            key = (method_id, method_version)
            if key in self._events:
                raise ValueError("method certification lifecycle already initialized")
            if not actor.strip() or not rationale.strip():
                raise ValueError("certification registration requires actor and rationale")
            event = MethodCertificationEvent(
                event_id=uuid.uuid4().hex, method_id=method_id,
                method_version=method_version, version=1, prior_state=None,
                state="experimental", actor=actor, rationale=rationale,
            )
            self._events[key] = [event]
            return event

    def state(self, method_id: str, method_version: str) -> CertificationState:
        with self._lock:
            events = self._events.get((method_id, method_version), ())
            return events[-1].state if events else "experimental"

    def transition(
        self, method_id: str, method_version: str, *, expected_version: int,
        state: CertificationState, actor: str, rationale: str,
        benchmark_report_ids: tuple[str, ...] = (),
        peer_review: PeerReviewArtifact | None = None,
    ) -> MethodCertificationEvent:
        with self._lock:
            key = (method_id, method_version)
            history = self._events.setdefault(key, [])
            prior = history[-1].state if history else None
            current = prior or "experimental"
            version = history[-1].version if history else 0
            if expected_version != version:
                raise ValueError(f"stale certification version: expected {version}, received {expected_version}")
            if not actor.strip() or not rationale.strip():
                raise ValueError("certification transitions require actor and rationale")
            if state not in self._TRANSITIONS[current]:
                raise ValueError(f"invalid certification transition: {current} -> {state}")
            reports = [self._reports.get(item) for item in benchmark_report_ids]
            if state in {"internal", "peer_reviewed", "reference_implementation"}:
                if not reports or any(report is None for report in reports):
                    raise ValueError("certification requires recorded benchmark reports")
                if any(
                    report.status != "passed" or (report.method_id, report.method_version) != key
                    for report in reports if report is not None
                ):
                    raise ValueError("certification requires passing reports for this exact method version")
            if state == "peer_reviewed" and (peer_review is None or peer_review.decision != "accepted"):
                raise ValueError("peer-reviewed status requires an accepted review artifact")
            if state == "reference_implementation" and current not in {"internal", "peer_reviewed"}:
                raise ValueError("reference implementation must follow internal or peer-reviewed state")
            event = MethodCertificationEvent(
                event_id=uuid.uuid4().hex, method_id=method_id,
                method_version=method_version, version=version + 1,
                prior_state=prior, state=state, actor=actor, rationale=rationale,
                benchmark_report_ids=benchmark_report_ids, peer_review=peer_review,
            )
            history.append(event)
            return event

    def history(self, method_id: str, method_version: str) -> tuple[MethodCertificationEvent, ...]:
        with self._lock:
            return tuple(self._events.get((method_id, method_version), ()))

    def reports(self, method_id: str, method_version: str) -> tuple[ReproducibilityReport, ...]:
        with self._lock:
            return tuple(
                report for report in self._reports.values()
                if (report.method_id, report.method_version) == (method_id, method_version)
            )

    def can_emit_findings(self, method_id: str, method_version: str) -> bool:
        return self.state(method_id, method_version) in {"peer_reviewed", "reference_implementation"}


class PluginDependency(Contract):
    name: str = Field(min_length=1)
    version_constraint: str = Field(min_length=1)
    optional: bool = False


class ScientificPluginManifest(Contract):
    package_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    platform_api_version: str = Field(min_length=1)
    method_ids: tuple[str, ...] = ()
    package_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    dependencies: tuple[PluginDependency, ...] = ()
    trust_level: Literal["unreviewed", "organization_reviewed", "trusted"] = "unreviewed"
    signature_status: Literal["not_provided", "unverified", "verified", "invalid"] = "not_provided"
    signature_reference: str | None = None
    sandbox: Literal["required", "declared", "not_sandboxed"] = "required"
    permissions: tuple[str, ...] = ()
    declared_compatibility: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def high_trust_requires_verified_signature(self) -> "ScientificPluginManifest":
        if self.trust_level == "trusted" and self.signature_status != "verified":
            raise ValueError("trusted plugin packages require a verified signature")
        if self.signature_status == "verified" and not self.signature_reference:
            raise ValueError("verified signature status requires a verification reference")
        return self


class SignatureVerifier(Protocol):
    verifier_id: str

    def verify(self, manifest: ScientificPluginManifest) -> tuple[bool, str]: ...


class PluginSignatureVerification(Contract):
    package_id: str
    package_sha256: str
    verifier_id: str
    verified: bool
    verification_reference: str
    verified_at: datetime = Field(default_factory=utc_now)


class ScientificPluginRegistry:
    """Register declarations only after compatibility and verifier checks.

    This registry never imports or executes package code. Sandbox enforcement is
    a deployment adapter responsibility and remains visible in the report.
    """

    def __init__(self) -> None:
        self._plugins: dict[tuple[str, str], tuple[ScientificPluginManifest, PluginSignatureVerification, PluginCompatibilityReport]] = {}
        self._lock = threading.RLock()

    def register(
        self, manifest: ScientificPluginManifest, *, verifier: SignatureVerifier,
        platform_api_version: str, installed_dependencies: dict[str, str],
    ) -> tuple[PluginSignatureVerification, PluginCompatibilityReport]:
        key = (manifest.package_id, manifest.version)
        with self._lock:
            if key in self._plugins:
                raise ValueError("scientific plugin package version already registered")
            verified, reference = verifier.verify(manifest)
            verification = PluginSignatureVerification(
                package_id=manifest.package_id, package_sha256=manifest.package_sha256,
                verifier_id=verifier.verifier_id, verified=verified,
                verification_reference=reference,
            )
            compatibility = check_plugin_compatibility(
                manifest, platform_api_version=platform_api_version,
                installed_dependencies=installed_dependencies,
            )
            if not verified and manifest.trust_level == "trusted":
                raise ValueError("trusted plugin cannot be registered without successful signature verification")
            if not compatibility.compatible:
                raise ValueError("scientific plugin is incompatible with this runtime")
            self._plugins[key] = (manifest, verification, compatibility)
            return verification, compatibility

    def all(self) -> tuple[tuple[ScientificPluginManifest, PluginSignatureVerification, PluginCompatibilityReport], ...]:
        with self._lock:
            return tuple(self._plugins[key] for key in sorted(self._plugins))


class PluginCompatibilityReport(Contract):
    package_id: str
    compatible: bool
    checked_platform_api_version: str
    dependency_status: dict[str, Literal["satisfied", "missing", "incompatible", "not_checked"]]
    limitations: tuple[str, ...] = ()


def check_plugin_compatibility(
    manifest: ScientificPluginManifest,
    *,
    platform_api_version: str,
    installed_dependencies: dict[str, str],
) -> PluginCompatibilityReport:
    dependency_status: dict[str, Literal["satisfied", "missing", "incompatible", "not_checked"]] = {}
    for dependency in manifest.dependencies:
        installed = installed_dependencies.get(dependency.name)
        if installed is None:
            dependency_status[dependency.name] = "missing" if not dependency.optional else "not_checked"
        elif installed == dependency.version_constraint:
            dependency_status[dependency.name] = "satisfied"
        else:
            dependency_status[dependency.name] = "incompatible"
    missing_required = any(
        dependency_status[item.name] in {"missing", "incompatible"}
        for item in manifest.dependencies if not item.optional
    )
    api_matches = manifest.platform_api_version == platform_api_version
    return PluginCompatibilityReport(
        package_id=manifest.package_id,
        compatible=api_matches and not missing_required,
        checked_platform_api_version=platform_api_version,
        dependency_status=dependency_status,
        limitations=("Dependency constraints currently require exact version equality; semantic-version ranges need a dedicated parser.",),
    )


class AuditEvent(Contract):
    event_id: str
    tenant_id: str = "local"
    aggregate_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    event_type: Literal["planning", "execution", "reasoning", "hypothesis_transition", "rule_execution", "evidence_change", "workflow_change", "assessment", "method_certification", "plugin_registration", "earth_object_materialized", "earth_object_relationship_asserted", "earth_object_candidate_rejected", "earth_object_restore_rejected"]
    actor: str = Field(min_length=1)
    occurred_at: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any]
    payload_sha256: str
    previous_event_sha256: str | None = None
    event_sha256: str


class AuditTrail(Protocol):
    def append(self, *, aggregate_id: str, event_type: str, actor: str, payload: dict[str, Any], tenant_id: str = "local") -> AuditEvent: ...
    def events(self, aggregate_id: str, *, tenant_id: str = "local") -> tuple[AuditEvent, ...]: ...


class InMemoryAuditTrail:
    """Thread-safe append-only hash-chained reference implementation."""

    def __init__(self) -> None:
        self._events: dict[tuple[str, str], list[AuditEvent]] = {}
        self._lock = threading.RLock()

    def append(self, *, aggregate_id: str, event_type: str, actor: str, payload: dict[str, Any], tenant_id: str = "local") -> AuditEvent:
        with self._lock:
            key = (tenant_id, aggregate_id)
            history = self._events.setdefault(key, [])
            payload_digest = canonical_digest(payload)
            previous = history[-1].event_sha256 if history else None
            event = AuditEvent(
                event_id=uuid.uuid4().hex, tenant_id=tenant_id,
                aggregate_id=aggregate_id, sequence=len(history) + 1,
                event_type=event_type, actor=actor, occurred_at=utc_now(),
                payload=payload, payload_sha256=payload_digest,
                previous_event_sha256=previous, event_sha256="0" * 64,
            )
            event_digest = canonical_digest(
                event.model_dump(mode="json", exclude={"event_sha256"})
            )
            event = event.model_copy(update={"event_sha256": event_digest})
            history.append(event)
            return event

    def events(self, aggregate_id: str, *, tenant_id: str = "local") -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._events.get((tenant_id, aggregate_id), ()))

    def verify(self, aggregate_id: str, *, tenant_id: str = "local") -> bool:
        events = self.events(aggregate_id, tenant_id=tenant_id)
        previous = None
        for sequence, event in enumerate(events, 1):
            data = event.model_dump(mode="json", exclude={"event_sha256"})
            if event.sequence != sequence or event.previous_event_sha256 != previous:
                return False
            if event.payload_sha256 != canonical_digest(event.payload):
                return False
            if event.event_sha256 != canonical_digest(data):
                # Event hash is calculated from canonical event fields with timestamp.
                return False
            previous = event.event_sha256
        return True


class InvestigationReproducibilityBundle(Contract):
    schema_version: str = "1.0.0"
    bundle_id: str
    investigation_id: str
    capability_matrix_revision: str | None = None
    hypotheses: tuple[dict[str, Any], ...] = ()
    plans: tuple[dict[str, Any], ...] = ()
    datasets: tuple[dict[str, Any], ...] = ()
    observations: tuple[dict[str, Any], ...] = ()
    provenance: tuple[dict[str, Any], ...] = ()
    scientific_methods: tuple[dict[str, Any], ...] = ()
    evidence_graph: dict[str, Any] | None = None
    reasoning_report: dict[str, Any] | None = None
    uncertainty_inventory: dict[str, Any] | None = None
    execution_trace: tuple[dict[str, Any], ...] = ()
    audit_events: tuple[dict[str, Any], ...] = ()
    missing_artifacts: tuple[str, ...] = ()
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    bundle_sha256: str
    exported_at: datetime = Field(default_factory=utc_now)


def build_reproducibility_bundle(
    *, investigation_id: str, capability_matrix_revision: str | None,
    hypotheses: Iterable[dict[str, Any]], plans: Iterable[dict[str, Any]],
    datasets: Iterable[dict[str, Any]], observations: Iterable[dict[str, Any]],
    provenance: Iterable[dict[str, Any]], scientific_methods: Iterable[dict[str, Any]],
    evidence_graph: dict[str, Any] | None, reasoning_report: dict[str, Any] | None,
    uncertainty_inventory: dict[str, Any] | None, execution_trace: Iterable[dict[str, Any]],
    audit_events: Iterable[dict[str, Any]],
) -> InvestigationReproducibilityBundle:
    artifacts: dict[str, Any] = {
        "hypotheses": tuple(hypotheses), "plans": tuple(plans), "datasets": tuple(datasets),
        "observations": tuple(observations), "provenance": tuple(provenance),
        "scientific_methods": tuple(scientific_methods), "evidence_graph": evidence_graph,
        "reasoning_report": reasoning_report, "uncertainty_inventory": uncertainty_inventory,
        "execution_trace": tuple(execution_trace), "audit_events": tuple(audit_events),
    }
    missing = tuple(key for key, value in artifacts.items() if value is None or value == ())
    hashes = {key: canonical_digest(value) for key, value in artifacts.items() if value is not None}
    identity = canonical_digest({"investigation_id": investigation_id, "capability_matrix_revision": capability_matrix_revision, "artifact_hashes": hashes})
    bundle = InvestigationReproducibilityBundle(
        bundle_id=f"repro-{identity[:24]}", investigation_id=investigation_id,
        capability_matrix_revision=capability_matrix_revision,
        hypotheses=artifacts["hypotheses"], plans=artifacts["plans"], datasets=artifacts["datasets"],
        observations=artifacts["observations"], provenance=artifacts["provenance"],
        scientific_methods=artifacts["scientific_methods"], evidence_graph=evidence_graph,
        reasoning_report=reasoning_report, uncertainty_inventory=uncertainty_inventory,
        execution_trace=artifacts["execution_trace"], audit_events=artifacts["audit_events"],
        missing_artifacts=missing, artifact_hashes=hashes, bundle_sha256="0" * 64,
    )
    return bundle.model_copy(update={"bundle_sha256": canonical_digest(bundle.model_dump(mode="json", exclude={"bundle_sha256", "exported_at"}))})
