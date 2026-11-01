# Model and method stack

SatQuery has model interfaces and an optional legacy computer-vision stack.
These are distinct from the deterministic Earth investigation path.

## Platform model interface

`platform.models` defines provider-neutral metadata and adapter/runtime
contracts for registering an inference implementation. The interface is an
extension point; the platform does not ship a general model router, model
marketplace, Earth foundation model, or model-driven scientific reasoner.

## Existing image capability

The original image question-answering application remains available through
compatibility API and CLI routes. Hugging Face/PyTorch dependencies are
optional (`pip install -e ".[vision]"`); some configurations may additionally
use the `large` extra. It operates on user-provided images and should not be
confused with broad satellite scene understanding, validated Earth Object
extraction, or EarthQuery-based observation.

The optional image fetcher obtains imagery from Esri World Imagery using
geocoding services for place names. It is a separate acquisition utility; its
availability, licensing, attribution, quotas, and terms are provider-bound.

## Scientific methods

Scientific method knowledge records cite published methods and describe
assumptions, applicability, limitations, and missing validation assets. The
records are catalog entries, not executable method implementations. The
reasoning path emits evidence-scoped diagnostics and only registered rules
can produce their declared findings; no method is considered scientifically
validated merely because a record or certification field exists.

See [scientific intelligence](SCIENTIFIC_INTELLIGENCE.md),
[implementation status](../IMPLEMENTATION_STATUS.md), and
[`research/PAPERS.md`](../research/PAPERS.md) for exact limits and references.
