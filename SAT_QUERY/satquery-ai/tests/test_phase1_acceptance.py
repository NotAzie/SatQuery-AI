r"""Phase 1 acceptance checks for SatQuery AI.

Contract checks run in the normal test suite with pixel-derived backend doubles.
Real-model checks are opt-in because they download/load checkpoints and require
an existing fetched image:

    $env:SATQUERY_RUN_REAL_ACCEPTANCE = "1"
    ..\.venv\Scripts\python.exe -m pytest tests/test_phase1_acceptance.py -q
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

import satquery
from satquery.config import Settings
from satquery.errors import QueryError
from satquery.orchestrator import SatQueryEngine
from satquery.schemas import Intent, ToolName

from conftest import make_scene, to_png_bytes

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "satquery-ai"
FETCHED_IMAGES = PACKAGE_ROOT / "data" / "fetched_images"
RUN_REAL = os.getenv("SATQUERY_RUN_REAL_ACCEPTANCE", "0").lower() in {"1", "true", "yes"}
REAL_QUERY_TIMEOUT_S = float(os.getenv("SATQUERY_ACCEPTANCE_QUERY_TIMEOUT", "30"))


def _upload(name: str = "scene.png") -> tuple[str, bytes]:
    return name, to_png_bytes(make_scene(urban_box=(230, 0, 384, 140)))


@pytest.fixture
def acceptance_engine(settings, vision) -> SatQueryEngine:
    """Use the deterministic pixel-derived suite for contract checks."""
    engine = SatQueryEngine(settings)
    engine.vision_suite = lambda: vision  # type: ignore[assignment]
    return engine


def _sample_image() -> Path | None:
    images = sorted(FETCHED_IMAGES.glob("*.jpg")) + sorted(FETCHED_IMAGES.glob("*.png"))
    return images[0] if images else None


def _require_real_prerequisites() -> Path:
    if not RUN_REAL:
        pytest.skip(
            "Real-model acceptance is opt-in; set SATQUERY_RUN_REAL_ACCEPTANCE=1 "
            "to load checkpoints and run image smoke tests."
        )
    image = _sample_image()
    if image is None:
        pytest.skip(
            f"No sample image exists under {FETCHED_IMAGES}; run the optional image fetcher first."
        )
    return image


def test_canonical_package_path_is_explicit_and_importable():
    """The installed/imported package must come from satquery-ai/satquery."""
    imported = Path(satquery.__file__).resolve()
    assert imported.parent.name == "satquery", f"Unexpected package path: {imported}"
    assert imported.parent.parent == PACKAGE_ROOT, (
        f"satquery imported from {imported}; expected the canonical package under {PACKAGE_ROOT}"
    )
    assert (PROJECT_ROOT / "archive" / "legacy_outer_modules").is_dir(), (
        "Duplicate outer modules are not quarantined under archive/legacy_outer_modules."
    )


def test_quality_profile_is_the_default_and_fast_is_explicit(monkeypatch):
    """Quality remains the default; fast mode must be an explicit opt-in."""
    for key in ("SATQUERY_PROFILE", "SATQUERY_CLIP_MODEL", "SATQUERY_GROUNDING_SCALES", "SATQUERY_GROUNDING_MAX_WINDOWS"):
        monkeypatch.delenv(key, raising=False)
    quality = Settings.from_env(dotenv_path=None)
    assert quality.profile == "quality"
    assert quality.clip_model == "openai/clip-vit-large-patch14"
    assert quality.grounding_max_windows == 320
    assert len(quality.grounding_scales) == 4

    monkeypatch.setenv("SATQUERY_PROFILE", "fast")
    fast = Settings.from_env(dotenv_path=None)
    assert fast.profile == "fast"
    assert fast.clip_model == "openai/clip-vit-base-patch32"
    assert fast.grounding_max_windows == 16
    assert fast.grounding_scales == (0.5,)


def test_tool_image_cardinality_rejects_missing_and_extra_images(acceptance_engine):
    """Tools must fail clearly instead of silently discarding supplied images."""
    with pytest.raises(QueryError, match="at least 2"):
        acceptance_engine.answer("What changed?", uploads=[_upload()])
    with pytest.raises(QueryError, match="accepts at most 1"):
        acceptance_engine.answer("Describe this scene", uploads=[_upload("a.png"), _upload("b.png")])
    with pytest.raises(QueryError, match="accepts at most 2"):
        acceptance_engine.answer(
            "What changed?",
            uploads=[_upload("a.png"), _upload("b.png"), _upload("c.png")],
        )


def test_health_and_capabilities_are_honest_before_models_are_loaded(monkeypatch):
    """Without loaded models, readiness and model-backed capabilities are false."""
    missing = {
        name: {"installed": False, "version": None}
        for name in ("torch", "transformers", "PIL", "numpy", "httpx", "accelerate", "sentencepiece")
    }
    monkeypatch.setattr("satquery.registry.probe_dependencies", lambda: missing)
    engine = SatQueryEngine(Settings.from_env(dotenv_path=None))

    health = engine.health()
    capabilities = {item.tool: item for item in engine.capabilities()}

    assert health["ready"] is False, "Health must not claim readiness without a usable backend."
    assert health["status"] == "degraded"
    assert all(
        not capabilities[tool].available
        for tool in (ToolName.CAPTION, ToolName.VQA, ToolName.SCENE, ToolName.GROUNDING, ToolName.MODALITY)
    )
    assert capabilities[ToolName.GROUNDING].unavailable_reason


@pytest.mark.real_acceptance
@pytest.mark.skipif(not RUN_REAL, reason="Set SATQUERY_RUN_REAL_ACCEPTANCE=1 for real-model acceptance.")
def test_warmup_health_capabilities_and_model_reuse():
    """Warmup must load models, expose readiness, and reuse object instances."""
    image = _require_real_prerequisites()
    engine = SatQueryEngine(Settings.from_env())

    before = engine.health()
    assert before["ready"] is False, "A fresh engine should not claim warmed readiness."

    warmup = engine.warmup()
    assert warmup["errors"] == {}, f"Warmup failed: {warmup['errors']}"
    assert set(("clip", "captioner", "vqa")).issubset(warmup["loaded"])
    assert warmup["ready"] is True

    after = engine.health()
    assert after["ready"] is True
    assert after["backends"]["practical"]["ready"] is True
    capabilities = {item.tool: item for item in engine.capabilities()}
    assert capabilities[ToolName.GROUNDING].available is True
    assert capabilities[ToolName.SCENE].available is True
    assert capabilities[ToolName.CAPTION].available is True

    clip_first = engine.registry.clip()
    caption_first = engine.registry.captioner()
    vqa_first = engine.registry.vqa()
    engine.warmup()
    assert engine.registry.clip() is clip_first
    assert engine.registry.captioner() is caption_first
    assert engine.registry.vqa() is vqa_first
    assert image.is_file()


@pytest.mark.real_acceptance
@pytest.mark.skipif(not RUN_REAL, reason="Set SATQUERY_RUN_REAL_ACCEPTANCE=1 for real-model acceptance.")
def test_post_warmup_caption_scene_and_grounding_smoke(monkeypatch):
    """Run practical smoke checks with the explicit latency-first profile.

    The quality-default contract is tested separately. This smoke test uses
    fast mode deliberately because a 320-window quality sweep is not a
    practical CPU acceptance check.
    """
    image = _require_real_prerequisites()
    monkeypatch.setenv("SATQUERY_PROFILE", "fast")
    monkeypatch.setenv("SATQUERY_CLIP_MODEL", "openai/clip-vit-base-patch32")
    monkeypatch.setenv("SATQUERY_GROUNDING_SCALES", "0.5")
    monkeypatch.setenv("SATQUERY_GROUNDING_MAX_WINDOWS", "16")
    monkeypatch.setenv("SATQUERY_GROUNDING_STRIDE_RATIO", "0.9")
    engine = SatQueryEngine(Settings.from_env())
    warmup = engine.warmup()
    assert warmup["ready"] is True, f"Warmup did not reach ready state: {warmup}"

    queries = (
        ("describe this scene", Intent.CAPTION),
        ("what type of scene is this", Intent.SCENE_CLASSIFICATION),
        ("where are the buildings", Intent.GROUNDING),
    )
    for query, expected_intent in queries:
        started = time.perf_counter()
        response = engine.answer(query, image_paths=[str(image)], include_trace=True)
        elapsed = time.perf_counter() - started
        print(f"PHASE1_LATENCY query={query!r} seconds={elapsed:.3f}")
        assert response.intent is expected_intent, f"{query!r} routed to {response.intent}"
        assert response.answer.strip(), f"{query!r} returned an empty answer"
        assert elapsed <= REAL_QUERY_TIMEOUT_S, (
            f"{query!r} took {elapsed:.2f}s, above the configured acceptance limit "
            f"of {REAL_QUERY_TIMEOUT_S:.2f}s after warmup"
        )
        assert all(step.status.value == "ok" for step in response.trace), (
            f"{query!r} had a failed trace step: {response.trace}"
        )
        if expected_intent is Intent.GROUNDING:
            assert response.results[0].regions, "Grounding completed but returned no regions."


def test_acceptance_configuration_is_self_describing():
    """Failure output points operators to the canonical commands and inputs."""
    assert PACKAGE_ROOT.is_dir(), f"Package root missing: {PACKAGE_ROOT}"
    assert (PACKAGE_ROOT / "pyproject.toml").is_file(), "pyproject.toml is missing from the package root."
    assert (PACKAGE_ROOT / "satquery" / "__main__.py").is_file(), "Canonical CLI entry point is missing."
