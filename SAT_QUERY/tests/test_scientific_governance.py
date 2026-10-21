import hashlib
import sqlite3

import pytest

from satquery.platform.scientific_governance import (
    AuditIntegrityError,
    BenchmarkCase,
    InMemoryAuditTrail,
    PeerReviewArtifact,
    ReferenceInvestigation,
    ScientificBenchmarkSuite,
    ScientificMethodCertificationLedger,
    ScientificPluginManifest,
    ScientificPluginRegistry,
    ScientificValidationExecutor,
    SQLiteAuditTrail,
    ValidationDatasetManifest,
    build_reproducibility_bundle,
    canonical_digest,
    reproducibility_report_digest,
)


def _suite():
    dataset = ValidationDatasetManifest(
        dataset_id="reference-set", version="1", content_sha256=hashlib.sha256(b"fixture bytes").hexdigest(),
        uri="https://example.test/reference", license="CC0-1.0",
        provenance={"curator": "test-fixture"}, partition="reference",
    )
    case = BenchmarkCase(
        case_id="case-1", reference_investigation_id="ref-investigation-1",
        input_manifest={"input": 2}, input_sha256=canonical_digest({"input": 2}),
        expected_output={"result": 4}, expected_output_sha256=canonical_digest({"result": 4}),
        validation_dataset_ids=("reference-set",), reference_ids=("fixture-reference",),
    )
    reference = ReferenceInvestigation(
        reference_investigation_id="ref-investigation-1", version="1",
        reproducibility_bundle_sha256="f" * 64,
        provenance={"source": "fixture-reference"},
        scientific_reference_ids=("fixture-reference",),
        benchmark_case_ids=("case-1",),
    )
    fields = {
        "suite_id": "fixture-suite", "version": "1", "method_id": "fixture.method",
        "method_version": "1.0", "domain": "climate",
        "validation_datasets": (dataset.model_dump(mode="json"),),
        "reference_investigations": (reference.model_dump(mode="json"),),
        "cases": (case.model_dump(mode="json"),),
        "scientific_references": ("fixture-reference",),
    }
    suite = ScientificBenchmarkSuite.model_validate({
        **fields, "suite_sha256": canonical_digest(fields),
    })
    return suite


class _Runner:
    runner_id = "test-runner"
    implementation_sha256 = "b" * 64

    def execute(self, case, _datasets):
        return {"result": case.input_manifest["input"] ** 2}


class _DatasetLoader:
    def load(self, manifest):
        return b"fixture bytes"


class _CorruptDatasetLoader:
    def load(self, manifest):
        return b"altered fixture bytes"


def test_validation_executes_reference_cases_and_binds_report_to_code_digest():
    suite = _suite()
    report = ScientificValidationExecutor().execute(
        suite, implementation_sha256="b" * 64, runner=_Runner(),
        dataset_loader=_DatasetLoader(),
        execution_environment={"python": "3.12"},
    )
    assert report.status == "passed"
    assert report.case_results[0].status == "passed"
    assert report.report_sha256 == reproducibility_report_digest(report)
    replay = ScientificValidationExecutor().execute(
        suite, implementation_sha256="b" * 64, runner=_Runner(),
        dataset_loader=_DatasetLoader(),
        execution_environment={"python": "3.12"},
    )
    assert replay.report_sha256 == report.report_sha256
    with pytest.raises(ValueError, match="does not match"):
        ScientificValidationExecutor().execute(
            suite, implementation_sha256="c" * 64, runner=_Runner(),
            dataset_loader=_DatasetLoader(),
            execution_environment={"python": "3.12"},
        )


def test_validation_rejects_changed_reference_dataset_bytes():
    report = ScientificValidationExecutor().execute(
        _suite(), implementation_sha256="b" * 64, runner=_Runner(),
        dataset_loader=_CorruptDatasetLoader(),
        execution_environment={"python": "3.12"},
    )
    assert report.status == "failed"
    assert report.case_results[0].status == "error"
    assert "integrity check failed" in report.case_results[0].explanation


def test_certification_requires_passed_reports_and_accepted_peer_review():
    suite = _suite()
    ledger = ScientificMethodCertificationLedger()
    registered = ledger.register(
        "fixture.method", "1.0", actor="registry",
        rationale="Registered for validation.", implementation_sha256="b" * 64,
    )
    with pytest.raises(ValueError, match="requires recorded benchmark reports"):
        ledger.transition(
            "fixture.method", "1.0", expected_version=1, state="internal",
            actor="reviewer", rationale="Promote after validation.",
        )
    report = ledger.execute_benchmark(
        suite, implementation_sha256="b" * 64, runner=_Runner(),
        dataset_loader=_DatasetLoader(),
        execution_environment={"python": "3.12"},
    )
    internal = ledger.transition(
        "fixture.method", "1.0", expected_version=1, state="internal",
        actor="reviewer", rationale="Reference benchmark passed.",
        benchmark_report_ids=(report.report_id,),
    )
    assert internal.version == 2 and not ledger.can_emit_findings("fixture.method", "1.0")
    peer_review = PeerReviewArtifact(
        review_id="review-1", reviewer="independent-reviewer", decision="accepted",
        reference_uri="https://example.test/review", comments_sha256="d" * 64,
    )
    peer = ledger.transition(
        "fixture.method", "1.0", expected_version=2, state="peer_reviewed",
        actor="editor", rationale="Review artifact accepted.",
        benchmark_report_ids=(report.report_id,), peer_review=peer_review,
    )
    assert peer.version == 3 and ledger.can_emit_findings("fixture.method", "1.0")
    restored = ScientificMethodCertificationLedger()
    restored.restore_event(registered)
    restored.restore_report(report)
    restored.restore_event(internal)
    restored.restore_event(peer)
    assert restored.can_emit_findings("fixture.method", "1.0")
    assert restored.reports("fixture.method", "1.0") == (report,)
    with pytest.raises(ValueError, match="differs from its certification history"):
        restored.bind_implementation("fixture.method", "1.0", "c" * 64)
    with pytest.raises(ValueError, match="stale"):
        ledger.transition(
            "fixture.method", "1.0", expected_version=2, state="deprecated",
            actor="editor", rationale="Stale update.",
        )


def test_audit_trail_is_ordered_per_tenant_and_hash_chain_verifiable():
    audit = InMemoryAuditTrail()
    first = audit.append(aggregate_id="investigation-1", event_type="planning", actor="planner", payload={"plan": "p1"})
    second = audit.append(aggregate_id="investigation-1", event_type="execution", actor="runtime", payload={"status": "complete"})
    other_tenant = audit.append(aggregate_id="investigation-1", tenant_id="org-b", event_type="planning", actor="planner", payload={"plan": "p2"})
    assert first.sequence == 1 and second.sequence == 2
    assert second.previous_event_sha256 == first.event_sha256
    assert audit.verify("investigation-1")
    assert audit.verify("investigation-1", tenant_id="org-b")
    assert len(audit.events("investigation-1")) == 2
    assert other_tenant.tenant_id == "org-b"
    with pytest.raises(ValueError):
        canonical_digest({"measurement": float("nan")})


def test_sqlite_audit_trail_persists_and_rejects_event_mutation(tmp_path):
    path = tmp_path / "audit.sqlite"
    audit = SQLiteAuditTrail(path)
    first = audit.append(
        aggregate_id="investigation-1", event_type="planning", actor="planner",
        payload={"plan": "p1"},
    )
    second = audit.append(
        aggregate_id="investigation-1", event_type="execution", actor="runtime",
        payload={"status": "complete"},
    )

    reopened = SQLiteAuditTrail(path)
    assert reopened.events("investigation-1") == (first, second)
    assert reopened.verify("investigation-1")
    assert second.previous_event_sha256 == first.event_sha256
    with sqlite3.connect(path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE satquery_audit_events SET event_json = '{}' "
            "WHERE aggregate_id = 'investigation-1'"
        )


def test_sqlite_audit_trail_detects_tampered_history_and_head(tmp_path):
    path = tmp_path / "audit.sqlite"
    audit = SQLiteAuditTrail(path)
    audit.append(
        aggregate_id="investigation-1", event_type="planning", actor="planner",
        payload={"plan": "p1"},
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE satquery_audit_heads SET event_sha256 = ? "
            "WHERE aggregate_id = ?",
            ("0" * 64, "investigation-1"),
        )
    assert audit.verify("investigation-1") is False
    with pytest.raises(AuditIntegrityError, match="head is inconsistent"):
        audit.events("investigation-1")


class _Verifier:
    verifier_id = "fixture-verifier"

    def verify(self, manifest):
        return True, f"verified:{manifest.package_sha256}"


def test_plugin_registry_checks_signature_compatibility_and_dependencies():
    manifest = ScientificPluginManifest(
        package_id="science-extension", version="1.0", platform_api_version="2",
        package_sha256="e" * 64, trust_level="trusted", sandbox="required",
        signature_status="verified", signature_reference="manifest-claim-not-trusted-by-itself",
        dependencies=({"name": "numpy", "version_constraint": "2.0"},),
    )
    registry = ScientificPluginRegistry()
    verification, compatibility = registry.register(
        manifest, verifier=_Verifier(), platform_api_version="2",
        installed_dependencies={"numpy": "2.0"},
    )
    assert verification.verified and compatibility.compatible
    assert len(registry.all()) == 1
    with pytest.raises(ValueError, match="incompatible"):
        registry.register(
            manifest.model_copy(update={"package_id": "bad-extension"}),
            verifier=_Verifier(), platform_api_version="2",
            installed_dependencies={"numpy": "1.0"},
        )


def test_reproducibility_bundle_hashes_present_artifacts_and_lists_gaps():
    bundle = build_reproducibility_bundle(
        investigation_id="investigation-1", capability_matrix_revision="matrix-r1",
        hypotheses=({"id": "h1"},), plans=({"plan": "p1"},), datasets=(),
        observations=(), provenance=(), scientific_methods=(), evidence_graph=None,
        reasoning_report=None, uncertainty_inventory=None, execution_trace=(), audit_events=(),
    )
    assert bundle.capability_matrix_revision == "matrix-r1"
    assert "datasets" in bundle.missing_artifacts
    assert bundle.artifact_hashes["hypotheses"] == canonical_digest(({"id": "h1"},))
    assert bundle.bundle_sha256 == canonical_digest(
        bundle.model_dump(mode="json", exclude={"bundle_sha256", "exported_at"})
    )
