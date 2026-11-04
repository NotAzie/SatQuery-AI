import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  InvestigationEarthViewDetails,
  InvestigationReproducibilityDetails,
  InvestigationReasoningDetails,
} from "./InvestigationRoute";

describe("investigation Earth view details", () => {
  const view = {
    context: {
      camera: { position: { lat: 10.25, lng: 20.5 } },
      imagery: [{ asset_id: "image-1" }],
      measurement: { kind: "distance", unit: "m", value: 125 },
    },
    source_session_exists: true,
    source_session_id: "session-1",
  };

  it("shows camera, presentation measurement, and source-session imagery", () => {
    const markup = renderToStaticMarkup(
      createElement(InvestigationEarthViewDetails, { view }),
    );

    expect(markup).toContain("10.2500, 20.5000");
    expect(markup).toContain("Presentation measurement: 125 m (distance)");
    expect(markup).toContain('alt="Session image image-1"');
    expect(markup).toContain("/vision/sessions/session-1/assets/image-1/thumbnail");
  });

  describe("investigation reproducibility details", () => {
    it("shows bundle identity, artifact integrity, missing items, and export action", () => {
      const markup = renderToStaticMarkup(
        createElement(InvestigationReproducibilityDetails, {
          bundle: {
            schema_version: "1.4.0",
            bundle_id: "repro-1",
            investigation_id: "investigation-1",
            capability_matrix_revision: null,
            capability_snapshots: [],
            hypotheses: [],
            plans: [],
            datasets: [],
            observations: [],
            earth_objects: [],
            earth_object_graph: null,
            earth_object_extractions: [],
            earth_object_transitions: [],
            provenance: [],
            scientific_methods: [],
            evidence_graph: null,
            reasoning_report: null,
            uncertainty_inventory: null,
            execution_trace: [],
            audit_events: [],
            monitoring_schedules: null,
            monitoring_runs: [],
            monitoring_events: [],
            monitoring_notifications: [],
            monitoring_comparisons: [],
            investigation_comparisons: [],
            missing_artifacts: ["plans"],
            artifact_hashes: { observations: "a".repeat(64) },
            bundle_sha256: "b".repeat(64),
            exported_at: "2026-11-04T10:00:00Z",
          },
        }),
      );

      expect(markup).toContain("Bundle SHA-256:");
      expect(markup).toContain("observations");
      expect(markup).toContain("plans");
      expect(markup).toContain("Download complete reproducibility bundle (JSON)");
    });
  });

  describe("investigation scientific reasoning details", () => {
    it("shows Engine-authored findings, evidence status, and limitations", () => {
      const markup = renderToStaticMarkup(
        createElement(InvestigationReasoningDetails, {
          response: {
            status: "evaluated",
            reasoning: {
              reasoning_id: "reasoning-1",
              investigation_id: "investigation-1",
              engine_id: "scientific-reasoning",
              engine_version: "1.0",
              status: "evaluated",
              findings: [
                {
                  finding_id: "finding-1",
                  rule_id: "shoreline-change",
                  rule_version: "1",
                  statement: "Observed evidence supports the hypothesis.",
                  hypothesis_statement: "The shoreline moved inland.",
                  evidential_relation: "supports",
                  observation_ids: ["observation-1"],
                  supporting_observation_ids: ["observation-1"],
                  contradicting_observation_ids: [],
                  unresolved_observation_ids: [],
                  assumptions: [],
                  limitations: ["A second date is needed."],
                },
              ],
              sufficiency: {
                status: "insufficient",
                explanation: "More method inputs are required.",
                applicable_validated_rule_ids: [],
                unmet_preconditions: ["a second observation"],
              },
              conclusion: {
                status: "findings_available",
                explanation: "The registered method produced a finding.",
                missing_evidence: ["A second observation"],
                additional_observation_targets: [],
              },
              limitations: ["The report does not quantify confidence."],
            },
          },
        }),
      );

      expect(markup).toContain("Observed evidence supports the hypothesis.");
      expect(markup).toContain("insufficient");
      expect(markup).toContain("observation-1");
      expect(markup).toContain("The report does not quantify confidence.");
    });

    it("explains when the Engine has not evaluated reasoning", () => {
      const markup = renderToStaticMarkup(
        createElement(InvestigationReasoningDetails, {
          response: { status: "not_evaluated", reasoning: null },
        }),
      );

      expect(markup).toContain(
        "The Engine has not produced a scientific reasoning report for this investigation.",
      );
    });
  });

  it("keeps image previews unavailable after the source session is deleted", () => {
    const markup = renderToStaticMarkup(
      createElement(InvestigationEarthViewDetails, {
        view: { ...view, source_session_exists: false },
      }),
    );

    expect(markup).toContain("1 image reference");
    expect(markup).not.toContain("<img");
  });
});
