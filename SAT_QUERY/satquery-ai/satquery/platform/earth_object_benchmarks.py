"""Reproducible regression runner for supplied Earth Object references.

Passing an exact-output benchmark establishes deterministic agreement with the
supplied reference bundle. It does not establish scientific validity, detection
accuracy, or applicability outside that bundle.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ..errors import ValidationError
from .contracts import Observation
from .earth_objects import EarthObjectExtractionPipeline, EarthObjectMaterializer
from .scientific_governance import BenchmarkCase, canonical_digest


class EarthObjectExtractionBenchmarkRunner:
    """Adapt canonical observation bundles to the governed benchmark runner.

    Each validation dataset must be UTF-8 JSON with the exact top-level shape::

        {"schema_version": "satquery.earth-object-observations.v1",
         "observations": [<canonical Observation>, ...]}

    The runner reconciles explicit candidates and materializes resulting
    objects. It neither detects entities nor assigns scientific confidence.
    """

    runner_id = "satquery.earth-object-extraction-benchmark-runner"

    def __init__(self, *, implementation_sha256: str) -> None:
        if not re.fullmatch(r"[a-fA-F0-9]{64}", implementation_sha256):
            raise ValueError("implementation_sha256 must be a 64-character SHA-256 digest")
        self.implementation_sha256 = implementation_sha256.casefold()

    def execute(self, case: BenchmarkCase, datasets: dict[str, bytes]) -> dict[str, Any]:
        if set(datasets) != set(case.validation_dataset_ids):
            raise ValueError("benchmark datasets do not exactly match the case manifest")
        observations: dict[str, Observation] = {}
        dataset_digests: dict[str, str] = {}
        for dataset_id in sorted(datasets):
            content = datasets[dataset_id]
            dataset_digests[dataset_id] = hashlib.sha256(content).hexdigest()
            try:
                document = json.loads(content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValidationError(
                    "Earth Object reference dataset is not valid UTF-8 JSON."
                ) from exc
            if (
                not isinstance(document, dict)
                or document.get("schema_version")
                != "satquery.earth-object-observations.v1"
                or not isinstance(document.get("observations"), list)
            ):
                raise ValidationError(
                    "Earth Object reference dataset has an unsupported schema."
                )
            for raw_observation in document["observations"]:
                observation = Observation.model_validate(raw_observation)
                existing = observations.get(observation.observation_id)
                if existing is not None and existing != observation:
                    raise ValueError(
                        "reference datasets bind one observation ID to different content"
                    )
                observations[observation.observation_id] = observation

        ordered = tuple(observations[key] for key in sorted(observations))
        investigation_id = case.input_manifest.get("investigation_id")
        if investigation_id is not None and not isinstance(investigation_id, str):
            raise ValueError("benchmark investigation_id must be a string when supplied")
        batch = EarthObjectExtractionPipeline().extract(
            ordered, investigation_id=investigation_id
        )
        observations_by_id = {item.observation_id: item for item in ordered}
        materializer = EarthObjectMaterializer()
        objects = tuple(
            materializer.materialize(
                declaration,
                tuple(
                    observations_by_id[observation_id]
                    for observation_id in declaration.observation_ids
                ),
            )
            for declaration in batch.declarations
        )
        return {
            "schema_version": "satquery.earth-object-extraction-output.v1",
            "pipeline_id": batch.pipeline_id,
            "pipeline_version": batch.pipeline_version,
            "declarations": tuple(
                item.model_dump(mode="json") for item in batch.declarations
            ),
            "issues": tuple(item.model_dump(mode="json") for item in batch.issues),
            "earth_objects": tuple(item.model_dump(mode="json") for item in objects),
            "dataset_sha256": dataset_digests,
            "input_observation_digests": batch.reproducibility[
                "input_observation_digests"
            ],
            "candidate_digests": batch.reproducibility["candidate_digests"],
            "output_sha256": canonical_digest(
                {
                    "declarations": tuple(
                        item.model_dump(mode="json") for item in batch.declarations
                    ),
                    "issues": tuple(
                        item.model_dump(mode="json") for item in batch.issues
                    ),
                    "earth_objects": tuple(
                        item.model_dump(mode="json") for item in objects
                    ),
                }
            ),
        }
