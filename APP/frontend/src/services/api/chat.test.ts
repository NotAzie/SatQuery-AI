import { afterEach, describe, expect, it, vi } from "vitest";

import {
  addInvestigationHypothesis,
  cancelAgentTurn,
  getInvestigationEvents,
  getInvestigationHypotheses,
  getInvestigationObservations,
  getInvestigationReasoning,
  getInvestigationReproducibility,
  streamAgentTurn,
  transitionInvestigationHypothesis,
} from "./chat";
import { apiUrl } from "./client";

describe("chat API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requests Engine cancellation through the session API", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);

    await cancelAgentTurn("platform/session");

    expect(fetch).toHaveBeenCalledWith(
      apiUrl("/chat/sessions/platform%2Fsession/cancel"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("reads Engine source observations through the session-owned investigation route", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            observation_id: "observation-1",
            source_id: "source-1",
            dataset: null,
            observed_at: null,
            geometry: null,
            bbox: null,
            crs: null,
            temporal_extent: null,
            observation_type: null,
            measured_variables: {},
            modalities: [],
            provenance: { citation: "Engine source" },
            uncertainty: {},
            provider_metadata: {},
            quality: {},
            confidence: null,
            reproducibility: {},
            properties: {},
            assets: {},
            source_document: {},
          },
        ]),
        { headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();

    const observations = await getInvestigationObservations(
      "session-1",
      "investigation-1",
      controller.signal,
    );

    expect(observations[0]?.observation_id).toBe("observation-1");
    expect(fetch).toHaveBeenCalledWith(
      apiUrl(
        "/chat/sessions/session-1/investigations/investigation-1/observations",
      ),
      expect.objectContaining({ signal: controller.signal }),
    );
  });

  it("requests the next paged Engine investigation journal sequence", async () => {
    const page = {
      investigation_id: "investigation-1",
      plan_id: "plan-1",
      events: [],
      next_sequence: 40,
      has_more: true,
    };
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(page), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);

    await expect(getInvestigationEvents("session-1", "investigation-1", 25, 50)).resolves.toEqual(
      page,
    );
    expect(fetch).toHaveBeenCalledWith(
      apiUrl(
        "/chat/sessions/session-1/investigations/investigation-1/events?after_sequence=25&limit=50",
      ),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("reads and mutates Engine-owned hypothesis lifecycle through the session API", async () => {
    const lifecycle = {
      status: "available",
      graph: { hypotheses: [] },
      events: [],
      restoration_error: null,
    };
    const mutation = {
      hypothesis: {
        hypothesis_id: "hypothesis-1",
        version: 1,
        proposition: "The shoreline moved inland.",
        source_text: "Researcher statement",
        origin: "explicit",
        lifecycle: "proposed",
        competing_group_id: null,
        parent_hypothesis_ids: [],
        composition: null,
        metadata: {},
      },
      events: [],
    };
    const fetch = vi.fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(lifecycle), {
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(mutation), {
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(mutation), {
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetch);
    const createBody = {
      hypothesis_id: "hypothesis-1",
      proposition: "The shoreline moved inland.",
      source_text: "Researcher statement",
      origin: "explicit" as const,
      competing_group_id: null,
      parent_hypothesis_ids: [],
      composition: null,
      actor: "Researcher",
      rationale: "Record the proposed explanation",
    };
    const transitionBody = {
      expected_version: 1,
      status: "active" as const,
      actor: "Researcher",
      rationale: "Begin review",
    };

    await expect(
      getInvestigationHypotheses("session-1", "investigation-1"),
    ).resolves.toEqual(lifecycle);
    await expect(
      addInvestigationHypothesis("session-1", "investigation-1", createBody),
    ).resolves.toEqual(mutation);
    await expect(
      transitionInvestigationHypothesis(
        "session-1",
        "investigation-1",
        "hypothesis-1",
        transitionBody,
      ),
    ).resolves.toEqual(mutation);
    expect(fetch).toHaveBeenNthCalledWith(
      1,
      apiUrl("/chat/sessions/session-1/investigations/investigation-1/hypotheses"),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      apiUrl("/chat/sessions/session-1/investigations/investigation-1/hypotheses"),
      expect.objectContaining({ method: "POST", body: JSON.stringify(createBody) }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      3,
      apiUrl(
        "/chat/sessions/session-1/investigations/investigation-1/hypotheses/hypothesis-1/transitions",
      ),
      expect.objectContaining({ method: "POST", body: JSON.stringify(transitionBody) }),
    );
  });

  it("reads Engine-authored scientific reasoning for an investigation", async () => {
    const response = {
      status: "evaluated",
      reasoning: {
        reasoning_id: "reasoning-1",
        investigation_id: "investigation-1",
        engine_id: "scientific-reasoning",
        engine_version: "1.0",
        status: "evaluated",
        findings: [],
        sufficiency: {
          status: "method_inputs_satisfied",
          explanation: "Declared method inputs are available.",
          applicable_validated_rule_ids: [],
          unmet_preconditions: [],
        },
        conclusion: {
          status: "findings_available",
          explanation: "A finding is available.",
          missing_evidence: [],
          additional_observation_targets: [],
        },
        limitations: [],
      },
    };
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(response), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);

    await expect(
      getInvestigationReasoning("session-1", "investigation-1"),
    ).resolves.toEqual(response);
    expect(fetch).toHaveBeenCalledWith(
      apiUrl(
        "/chat/sessions/session-1/investigations/investigation-1/reasoning",
      ),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("reads the Engine reproducibility bundle through the session API", async () => {
    const bundle = {
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
    };
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(bundle), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);

    await expect(
      getInvestigationReproducibility("session-1", "investigation-1"),
    ).resolves.toEqual(bundle);
    expect(fetch).toHaveBeenCalledWith(
      apiUrl(
        "/chat/sessions/session-1/investigations/investigation-1/reproducibility",
      ),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("submits selected image asset references with the chat turn", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(
        'data: {"type":"engine.event"}\n\n',
        { headers: { "Content-Type": "text/event-stream" } },
      ),
    );
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();
    const stream = streamAgentTurn(
      "session-1",
      {
        message: "Describe this image",
        asset_ids: ["asset-1"],
      },
      controller.signal,
    );

    await stream.next();

    expect(fetch).toHaveBeenCalledWith(
      apiUrl("/chat/sessions/session-1/turns"),
      expect.objectContaining({
        body: JSON.stringify({
          message: "Describe this image",
          asset_ids: ["asset-1"],
        }),
      }),
    );
  });
});
