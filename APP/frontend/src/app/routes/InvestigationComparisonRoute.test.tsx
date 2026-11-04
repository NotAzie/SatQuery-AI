import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type {
  EngineEarthObjectGeoJSON,
  EngineInvestigationComparison,
  EngineObservation,
} from "@/shared/types";

import {
  EngineInvestigationComparisonSummary,
  InvestigationComparisonColumn,
} from "./InvestigationComparisonRoute";

function dataFor(investigationId: string, evidenceId: string) {
  const observation: EngineObservation = {
    assets: {},
    bbox: null,
    confidence: null,
    crs: null,
    dataset: null,
    geometry: null,
    measured_variables: {},
    modalities: [],
    observation_id: `observation-${investigationId}`,
    observation_type: null,
    observed_at: null,
    properties: {},
    provenance: {},
    provider_metadata: {},
    quality: {},
    reproducibility: {},
    source_document: {},
    source_id: `source-${investigationId}`,
    temporal_extent: null,
    uncertainty: {},
  };
  const earthObjects: EngineEarthObjectGeoJSON = {
    features: [
      {
        type: "Feature",
        id: `object-${investigationId}`,
        geometry: { type: "Point", coordinates: [0, 0] },
        properties: {
          evidence_ids: [evidenceId],
          investigation_ids: [investigationId],
          lifecycle: null,
          object_id: `object-${investigationId}`,
          object_type: "site",
          revision: 1,
          source_observation_ids: [observation.observation_id],
        },
      },
    ],
    "satquery:geometry_policy": "engine",
    "satquery:omitted_objects": [],
    type: "FeatureCollection",
  };
  return {
    ref: { investigation_id: investigationId, session_id: `session-${investigationId}` },
    report: {
      investigation_id: investigationId,
      markdown: `Report for ${investigationId}`,
      report_id: `report-${investigationId}`,
      report_sha256: "a".repeat(64),
    },
    observations: [observation],
    earthObjects,
    events: {
      investigation_id: investigationId,
      plan_id: null,
      events: [],
      has_more: false,
      next_sequence: 0,
    },
  };
}

describe("investigation comparison", () => {
  it("presents Engine reports, source IDs, evidence IDs, and journal context without synthesis", () => {
    const markup = renderToStaticMarkup(
      createElement(
        MemoryRouter,
        null,
        createElement(InvestigationComparisonColumn, {
          side: "First",
          data: dataFor("investigation-1", "evidence-1"),
        }),
      ),
    );

    expect(markup).toContain("Report for investigation-1");
    expect(markup).toContain("observation-investigation-1");
    expect(markup).toContain("source-investigation-1");
    expect(markup).toContain("evidence-1");
    expect(markup).toContain("Complete ordered journal.");
    expect(markup).not.toContain("difference");
    expect(markup).not.toContain("better");
  });

  it("presents the Engine comparison digest, output, and limitations", () => {
    const comparison: EngineInvestigationComparison = {
      comparison_id: "investigation-comparison-1",
      comparison_sha256: "b".repeat(64),
      schema_version: "1.2",
      stack_builder_version: "1.1.0",
      temporal_method_id: "satquery.temporal.consecutive-difference",
      temporal_method_version: "1.0.0",
      investigation_reports: [],
      measurement_groups: [],
      observation_stacks: [],
      temporal_diagnostics: [],
      alignment_issues: [],
      temporal_issues: [],
      observation_identity_conflicts: [],
      unmatched_observation_ids: [],
      limitations: ["No scientific conclusions are generated."],
      markdown: "# Engine-authored comparison",
    };
    const markup = renderToStaticMarkup(
      createElement(EngineInvestigationComparisonSummary, { comparison }),
    );

    expect(markup).toContain("Engine-authored scientific comparison");
    expect(markup).toContain("b".repeat(64));
    expect(markup).toContain("# Engine-authored comparison");
    expect(markup).toContain("No scientific conclusions are generated.");
  });
});
