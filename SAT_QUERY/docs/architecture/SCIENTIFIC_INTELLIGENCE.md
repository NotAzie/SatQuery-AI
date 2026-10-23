# Scientific Investigation Intelligence

## Role in the platform

The deterministic investigation planner parses the request and resolves only
parameters supported by explicit text, ontology declarations, or a structured
`EarthQuery`. The intelligence layer then turns that plan into evidence
collection strategies before the perception engine is called:

```text
Question -> InvestigationPlan -> InvestigationDesign -> Perception -> EvidenceAssessment -> ScientificReasoningReport
```

`InvestigationIntelligenceEngine` is separate from the planner and perception
engine. It links each declared evidence requirement to one or more planned
observation steps. A strategy is executable only when the plan is ready, the
candidate has selected implementations, every requirement maps to a step, and
the capability plan reports no unavailable requested variable or modality.
The typed investigation evidence graph carries these links through execution:
plan requirements can be linked to planned steps and, when a declared
measurement or modality is present, to observation identifiers. Graph edges
describe traceability (`requires`, `planned_by`, `observed_in`, `reports`); no
edge claims that an observation supports a scientific hypothesis.

## Evidence assessment boundary

After execution, the same engine can audit the result against the selected
candidate. It reports whether returned observation metadata declares requested
variables and modalities, whether requirements are missing or indeterminate,
the observation identifiers involved, and conflicts already reported by
perception fusion.

This is **coverage auditing**, not scientific sufficiency. Presence of a
variable or modality does not establish measurement validity, representativeness,
causality, or support for a hypothesis. Spatial and temporal requirements are
kept indeterminate because the current assessment does not verify full geometry
intersection or interval coverage. Hypotheses are preserved verbatim and stay
unevaluated until a versioned, domain-appropriate test operator is registered.
No confidence or probability is produced.

## Initial scientific reasoning engine

`satquery.platform.reasoning` adds a provider-neutral reasoning boundary. A
versioned operator registry runs deterministic evidence diagnostics, while a
separate versioned rule registry is the only extension point allowed to emit
scientific findings. The built-in operators currently report declared evidence
completeness, represented missing requirements, and conflicts passed through
from perception. Measurement compatibility reports only exact canonical-name
and declared-unit groups; temporal alignment reports interval overlap from
explicit timestamps or extents; spatial alignment reports bbox intersection
only for matching declared CRSs. These are structural diagnostics, not
hypothesis tests or evidence of physical agreement.

Every hypothesis carried by the investigation design receives an independent
evaluation record. The default rule registry is empty, so the current default
conclusion is explicitly unresolved. Confidence is fixed to `null`, and
uncertainty is marked `not_quantified`; neither is inferred from coverage or
metadata.

Scientific rules carry a `ScientificRuleManifest` with validation state,
implementation digest, scientific references, required evidence, applicability
conditions, dataset compatibility, observation-quality requirements, and an
uncertainty propagation declaration. A rule marked validated must include a
validation record whose implementation digest matches the manifest and whose
references exist in the manifest. Experimental and draft rules remain visible
through the scientific-method catalog but are never invoked for conclusions.
Before execution, the engine checks declared variables, modalities, sample
count, temporal/spatial support, dataset declarations, and quality thresholds.
Rule or operator exceptions are recorded by type in the reasoning trace and do
not retroactively fail successful acquisition.

Rules return typed `ScientificRuleResult` values. The engine rejects outputs
that misidentify the rule, version, hypothesis, or observations. Directional
findings require observation IDs; the engine attaches source provenance and
declared observation uncertainty. Conclusions expose supporting,
contradicting, unresolved, missing, and additional-observation targets
separately, with an ordered trace. The engine does not aggregate evidence
weights or rank hypotheses. A log-likelihood ratio is retained only when a
validated method supplies calibration references and dependence grouping.
Priors and cross-method dependence handling are not implemented, so no
posterior is calculated.

Uncertainty propagation is an explicit versioned extension point. A validated
rule may declare propagation required and name a method; without that registered
method, the rule remains insufficient for a directional finding. No default
method invents uncertainty or confidence. The sufficiency assessment concerns
only whether a validated method's declared inputs are present, not whether the
evidence is scientifically sufficient for a conclusion.

`Observation.canonical_measurements` is an additive typed view produced by
semantic normalization. It keeps source variable, value, source unit, metadata,
ontology reference, semantic-resolution status, and observation ID. It does not
convert units or assert comparability. Existing `measured_variables` and
provider metadata remain intact. Reasoning operators must decline comparison
when their declared semantic, temporal, spatial, or unit preconditions are not
met.

The report is available from
`GET /api/v1/platform/investigations/{id}/reasoning`, is included in the
investigation intelligence payload, and is shown in the browser workspace and
CLI investigation inspection. The runtime retains the current report in
process memory and indexes each produced report as an Earth Memory artifact;
SQLite Earth Memory can preserve those artifacts across local restarts. The
route selects the current/latest report, while prior indexed reports remain
searchable. Signed reproducibility manifests and distributed history are not
provided.

## Inference bookkeeping and lifecycle

The reasoning report now includes a deterministic hypothesis graph. Hypothesis
identifiers are derived from their preserved source text and proposition. A
separate `HypothesisLifecycleLedger` records proposed, active, review,
superseded, withdrawn, and closed states with optimistic version checks and
append-only transition events. Investigations initialize planner hypotheses as
proposed and then active; explicitly added hypotheses begin proposed and must
be transitioned before rule evaluation. Composite hypotheses require explicit
parents and an `all` or `any` composition, and dependency graphs reject
unknown nodes and cycles. The current evaluator does not yet calculate a
composite proposition's truth from its children. Lifecycle storage is
in-process and must be replaced with a durable repository for multi-worker or
restart-safe use.

`EvidenceEvaluationEngine` reports quality declarations, provenance presence,
dataset identity, explicit dataset trust assertions, and explicit observation
independence assertions as separate fields. Missing trust or independence stays
`not_assessed`/`unknown`; no reliability score is synthesized. Provider count,
modality diversity, or different dataset identifiers alone do not establish
independent evidence or corroboration. Trust assertions are supplied by an
external review process; the runtime does not independently certify their
basis or cited references. A rule that depends on a trust domain must list its
machine-readable `required_trust_scope_ids`; those scopes are enforced as
applicability conditions and missing or rejected assessments prevent rule
execution. Trust assessment IDs and versions are included in report evidence
lineage.

`UncertaintyBudgetEngine` inventories measurement, dataset, model, and
reasoning uncertainty separately. It preserves untyped observation uncertainty
as uninterpreted source metadata. Quantified components require a value, unit,
and versioned method. The budget does not combine components unless a future
registered method declares compatible units, distributions, dependencies, and
propagation semantics. The report distinguishes a component inventory from
propagated uncertainty.

`AlternativeExplanationEngine` only compares hypotheses in an explicitly
declared competing group; it does not generate alternatives or assume that a
group is exhaustive or mutually exclusive. `InvestigationRefinementEngine`
turns declared missing evidence requirements into stable recommendation
records. It does not invent a variable, modality, or dataset choice: dataset
selection is deferred to capability planning, and modality is left
unassigned unless the requirement names one. Lifecycle history is inspectable
through the hypotheses API and `satquery hypotheses show`.

`ObservationAgreementOperator` compares finite numeric measurements only when
canonical variables and unit strings match exactly and a caller registers a
versioned, referenced absolute/relative tolerance. Comparisons additionally
require exact declared geometry, CRS, and timezone-aware acquisition timestamp
matches; unresolved or different support is reported as an alignment blocker,
not compared. This conservative identity check does not prove equivalent sensor
footprints or temporal aggregation. The default criterion set is empty. Results
mean agreement under that declared criterion, not evidence of independence or
scientific corroboration.

This is an auditable inference framework, not yet a populated scientific
inference library. No domain rule is currently marked validated. Domain-
specific temporal, spatial, statistical, causal, uncertainty, and sampling-bias
methods need independent validation before they can produce substantive Earth
science conclusions. Alternative hypotheses are preserved when supplied; the
platform does not invent scientific alternatives from free text. Planner
hypotheses are preserved as propositions and explicit hypotheses can be added
through the lifecycle API. Structured scientific semantics (variables,
direction, spatial/temporal scope, null model, and falsification criteria) are
still needed before broad automatic inference can be trusted.

## Extensibility boundary

## Scientific governance and reproducibility

The runtime now has a separate scientific-method certification ledger. A
manifest's `validation_status` and a declared validation record are metadata;
they do not grant platform execution authority. Platform runtime rules begin in
`experimental` and can emit findings only after reaching `peer_reviewed` or
`reference_implementation` through certification transitions. `internal`,
`deprecated`, and `retired` versions remain inspectable but cannot produce
platform findings. Transitions are append-only, version checked, actor and
rationale attributed, and bound to passing reports for the exact method
version. Peer-reviewed status also requires an accepted review artifact.
The reasoning engine denies findings by default when no certification policy is
injected. Unit-level extension tests that intentionally isolate rule mechanics
must supply an explicit test certification policy; the platform runtime uses
the append-only certification ledger.

Benchmark suites bind a versioned method to content-addressed validation data,
reference investigation cases, expected output payloads, and cited sources.
Validation executes each case through a registered runner whose implementation
digest must match the registered method. The executor loads each referenced
dataset through an injected loader, verifies its content digest, and passes the
verified bytes to the runner. Each reference investigation has a versioned
bundle digest. The initial comparator requires exact
canonical output equality; it invents no tolerances. Failures and runner errors
are recorded in a reproducibility report. No benchmark suites or datasets are
shipped as scientific truth. Independent dataset curation and validation
remain external responsibilities.

Scientific plugin manifests describe package digest, compatibility, dependency
constraints, trust level, signature state, permissions, and sandbox posture.
`ScientificPluginRegistry` calls a replaceable signature verifier and checks
compatibility but never imports or executes package code. The current
dependency checker supports exact version equality only, and sandbox
enforcement belongs to a deployment adapter. A claimed trust level in a
manifest is not itself verification.

`InMemoryAuditTrail` records planning, execution, assessment, reasoning, rule
execution, hypothesis transitions, workflow changes, method certification,
and plugin registration as per-aggregate hash chains. Investigation and plan
chains are readable through the audit API. The runtime also exports a
versioned reproducibility bundle containing retained hypotheses, plans,
dataset references, observations, provenance, method manifests, evidence
graph, reasoning report, uncertainty inventory, execution task trace, audit
events, capability-matrix revision and its safe selection snapshot,
missing-artifact list, and per-artifact hashes. Snapshots have an independent
content digest and omit raw dataset metadata, asset URIs, and connector
source/provider payloads. Missing source artifacts are called out rather than
reconstructed.

Audit events can use the default in-memory trail or the configured local
SQLite audit adapter. This is durable single-host storage, not a distributed
transactional event service. Signed attestations, independent reviewer
identity, immutable snapshots of raw upstream data, sandbox runtime,
range-aware dependency solver, and benchmark comparators for scientifically
justified tolerances remain absent. The capability snapshot records the public
selection view, not the source payloads or acquired data required to recreate
an upstream response. The hash chain detects accidental or partial changes
but is not a signature and cannot protect against an administrator rewriting
the entire store.

## Scientific knowledge and workflow scaffolds

`platform.scientific_knowledge` adds a versioned scientific method catalog over
the executable scientific-rule contract. Registration preserves the rule
validation record and implementation digest, and runtime rule registration
also adds the matching method entry. The catalog exposes ten Earth-science
domain namespaces. An empty domain is explicitly reported as having no
validated methods; the namespace is not a claim of implemented science.
Method capability preflight checks validation state, requested resolved
variables and modalities, declared dataset metadata, query time bounds, CRS,
quality declarations, and uncertainty metadata against one capability-matrix
revision. This is a metadata preflight, not a guarantee of successful
acquisition or scientific applicability. A method is rejected when required
capabilities cannot be verified; unsupported dimensions must not be inferred.

Scientific operator manifests enumerate the requested test families but force
unbacked outputs to remain diagnostic-only. Claiming validated-method output
requires an explicit versioned method and references. Evidence weight records
are categorical declarations tied to an assessor and basis; numeric weights
and probabilities remain absent. Dependency edges preserve explicit
independent/dependent/unknown assessments. Evidence aggregation requires an
explicit versioned method and records its assumptions and dependence handling.

The ten domain investigation templates are deliberately configuration-only
structures. They declare generic workflow stages and unresolved configuration
slots without prescribing scientific variables, thresholds, datasets, or
conclusions. API and CLI (`satquery science methods` and
`satquery science workflows`) expose the catalogs for inspection. Independent
scientific review and a reproducible validation suite remain prerequisites for
populating these catalogs with methods.

The method registry and workflow templates are currently in-process runtime
objects. The method registry is revisioned, but there is no signed package
format, external scientific-review workflow, durable registry backend, or
cryptographic attestation of the catalog itself. These become important before
multi-worker deployment or broad third-party method distribution.

## Extensibility boundary

Future analysis operators should declare their domain, input evidence
requirements, assumptions, units, applicability conditions, output semantics,
and reproducibility metadata. The platform should reject an operator when its
preconditions are not met, and retain the operator version and input evidence
IDs with every result. Probabilistic and model-assisted components must be
replaceable adapters whose outputs are distinguishable from deterministic
checks and source observations.

Plans, designs, assessments, and reasoning reports are available through the
runtime and are indexed as memory artifacts when produced. Default stores are
in process; configured SQLite adapters can retain supported lifecycle and
memory artifacts across local restarts. This persistence does not provide a
distributed transaction across acquisition, analysis, and all stores.

## Cited method knowledge, sufficiency, and Earth Memory

The cited method library is separate from the executable scientific-rule
registry and from certification. Its initial records cover seven narrow
literature-backed cases: revised Landsat DSWE partial-surface-water tests,
SPI, CONUS CBI burn-severity regression, the NLCD 2016 production workflow,
geodetic point glacier surface mass balance, Tucker's vegetation index, and a
South England Landsat harmonic urban-growth case study. The catalog has no
seed records yet for climatology, ecology as a domain, flood, oceanography,
agriculture, or several other registered domains. These are cited knowledge
records, not SatQuery implementations. Each record preserves its published
validation scope and limitations; SPI is marked method-definition-only.
None has a SatQuery implementation, materialized benchmark suite,
certification, or executable uncertainty propagation. A DOI or external
reference is not a local validation run.

The deterministic method evidence assessor checks required measurements and
units, declared modalities, requested spatial/temporal coverage, provenance
presence, required uncertainty categories, dataset identity, certification,
and benchmark status. It returns `sufficient`, `insufficient`, or
`indeterminate`; unverified geometry unions, dataset-description equivalence,
or external benchmark references remain unknown. Refinement returns explicit
missing-evidence recommendations and capability-matrix matches. It never
acquires observations. This is precondition assessment, not proof that the
scientific method will produce a valid conclusion.

Earth Memory has a storage-neutral repository protocol, an in-memory adapter,
and an opt-in SQLite adapter. SQLite stores immutable, content-hashed snapshots
in transactions, persists explicit source-artifact links, exposes a schema
version, and verifies stored record/search-index checks on read and through an
integrity report. Both adapters share deterministic literal search semantics
and produce the same content-derived index revision for the same artifact set.
Runtime re-indexing of unchanged artifacts is idempotent and preserves their
original index timestamp. SQLite supports concurrent local processes through
WAL and bounded busy waits; it is not a distributed or encrypted store. There
is no semantic ranking, cross-investigation inference, or learning.

The seed sources include [Jones (2019), revised DSWE partial-surface-water
tests](https://pubs.usgs.gov/publication/70202237), [McKee, Doesken, and
Kleist (1993), SPI time scales](https://ccc.atmos.colostate.edu/pdfs/relationshipofdroughtfrequency.pdf),
[Picotte et al. (2021), regional-to-CONUS burn-severity models](https://pubs.usgs.gov/publication/70221893),
[Yang et al. (2018), NLCD 2016 methodology](https://pubs.usgs.gov/publication/70245784),
[Vincent et al. (2021), geodetic point glacier mass balance](https://tc.copernicus.org/articles/15/1259/2021/index.html),
[Tucker (1979), vegetation radiance indices](https://doi.org/10.1016/0034-4257(79)90013-0),
and the [Landsat harmonic urban-growth case study](https://doi.org/10.3390/rs13163339).
