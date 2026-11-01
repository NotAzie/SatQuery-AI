"""Specialist tools, run against real synthetic imagery.

The backends are doubles, but they derive everything from pixels, so these
tests verify the actual algorithms: that grounding puts the box where the
content is, that scene classification notices a mixed scene, that change
detection separates a structural edit from a brightness shift.
"""

from __future__ import annotations

import numpy as np
import pytest

from satquery.errors import QueryError
from satquery.imaging import apply_modality, load_image_from_bytes
from satquery.schemas import BackendKind, Modality, ToolName
from satquery.tools import build_tools
from satquery.tools.base import ResultCache, ToolContext

from conftest import make_sar_scene, make_scene, to_png_bytes


@pytest.fixture
def tools():
    return build_tools()


def build_context(
    images, settings, vision, *, query="describe this", target=None, arguments=None
) -> ToolContext:
    cache = ResultCache(settings.cache_size)
    context = ToolContext(
        query=query,
        images=images,
        settings=settings,
        vision=vision,
        cache=cache,
        target=target,
        arguments=dict(arguments or {}),
    )

    registry = build_tools()

    def invoke(tool_name: ToolName, call_arguments):
        nested = ToolContext(
            query=context.query,
            images=context.images,
            settings=context.settings,
            vision=context.vision,
            cache=context.cache,
            target=call_arguments.get("target", context.target),
            arguments=dict(call_arguments),
            warnings=context.warnings,
            invoke=invoke,
        )
        tool = registry[tool_name]
        tool.validate(nested)
        return tool.run(nested)

    context.invoke = invoke
    return context


def load(image, settings, name="scene.png", hint=None):
    loaded = load_image_from_bytes(to_png_bytes(image), name, settings)
    return apply_modality(loaded, hint)


# ---------------------------------------------------------------------------
# Modality
# ---------------------------------------------------------------------------


def test_modality_tool_reports_optical_with_evidence(tools, settings, vision, water_corner_scene):
    image = load(water_corner_scene, settings)
    context = build_context([image], settings, vision, query="is this optical or radar?")

    result = tools[ToolName.MODALITY].run(context)

    assert result.ok
    assert result.data["modality"] == Modality.OPTICAL.value
    assert "mean_channel_spread" in result.data["evidence"]
    assert result.data["evidence"]["texture"]["mean_intensity"] > 0
    assert "optical" in result.summary.lower()


def test_modality_tool_flags_sar_and_warns_about_colour(tools, settings, vision):
    image = load(make_sar_scene(), settings, name="sar.png")
    context = build_context([image], settings, vision)

    result = tools[ToolName.MODALITY].run(context)

    assert result.data["modality"] == Modality.SAR.value
    assert "radar" in result.summary.lower()
    assert "colour" in result.summary.lower()


def test_modality_tool_works_without_an_embedding_backend(tools, settings, water_corner_scene):
    from satquery.backends.base import VisionSuite
    from conftest import FakeCaptioner, FakeAnswerer

    vision = VisionSuite(embedder=None, captioner=FakeCaptioner(), answerer=FakeAnswerer(), strong=None)
    image = load(water_corner_scene, settings)
    context = build_context([image], settings, vision)

    result = tools[ToolName.MODALITY].run(context)
    assert result.ok
    assert result.backend is BackendKind.NONE


# ---------------------------------------------------------------------------
# Scene classification
# ---------------------------------------------------------------------------


def test_scene_classification_ranks_and_groups_labels(tools, settings, vision, mixed_scene):
    image = load(mixed_scene, settings)
    context = build_context([image], settings, vision, query="what land use is this")

    result = tools[ToolName.SCENE].run(context)

    assert result.ok
    assert len(result.labels) == 5
    scores = [label.score for label in result.labels]
    assert scores == sorted(scores, reverse=True)
    assert all(label.group for label in result.labels)
    assert result.data["group_mixture"]
    assert result.data["taxonomy_size"] > 30


def test_scene_classification_detects_a_mixed_footprint(tools, settings, vision, mixed_scene):
    image = load(mixed_scene, settings)
    context = build_context([image], settings, vision)

    result = tools[ToolName.SCENE].run(context)

    assert result.data["distinct_tile_labels"] >= 2
    assert "mixed scene" in result.summary


def test_scene_classification_is_cached_within_a_context(tools, settings, vision, water_corner_scene):
    image = load(water_corner_scene, settings)
    context = build_context([image], settings, vision)
    tool = tools[ToolName.SCENE]

    tool.run(context)
    calls_after_first = vision.embedder.image_calls
    tool.run(context)

    assert vision.embedder.image_calls == calls_after_first
    assert context.cache.stats()["hits"] >= 1


def test_scene_classification_uses_sar_templates_for_radar(tools, settings, vision):
    image = load(make_sar_scene(), settings, name="sar.png")
    context = build_context([image], settings, vision)

    result = tools[ToolName.SCENE].run(context)
    assert result.data["prompt_templates"] == 4  # the SAR template set


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------


def test_grounding_localises_water_in_the_correct_corner(tools, settings, vision, water_corner_scene):
    image = load(water_corner_scene, settings)
    context = build_context(
        [image], settings, vision, query="where is the water", target="water"
    )

    result = tools[ToolName.GROUNDING].run(context)

    assert result.ok
    assert result.data["present"] is True
    assert result.regions, "expected at least one region over the water body"

    leader = result.regions[0]
    centre_x, centre_y = leader.centroid
    assert centre_x < 0.5 and centre_y < 0.5, f"region landed at {leader.centroid}"
    assert "top" in leader.placement and "left" in leader.placement


def test_grounding_reports_absence_rather_than_inventing_a_box(tools, settings, vision):
    # A uniform bare-soil scene contains no water at all.
    image = load(make_scene(width=256, height=256), settings)
    context = build_context([image], settings, vision, target="water")

    result = tools[ToolName.GROUNDING].run(context)

    assert result.data["present"] is False
    assert result.regions == []
    assert "no region" in result.summary.lower()


def test_grounding_without_a_target_is_refused(tools, settings, vision, water_corner_scene):
    image = load(water_corner_scene, settings)
    context = build_context([image], settings, vision, target=None)

    with pytest.raises(QueryError) as excinfo:
        tools[ToolName.GROUNDING].run(context)
    assert excinfo.value.remediation


def test_grounding_records_its_method_honestly(tools, settings, vision, water_corner_scene):
    image = load(water_corner_scene, settings)
    context = build_context([image], settings, vision, target="water")

    result = tools[ToolName.GROUNDING].run(context)

    assert "contrast set" in result.data["method"]
    assert "not object instances" in result.data["granularity"]
    assert result.data["windows_scored"] > 0
    assert len(result.data["contrast_phrases"]) >= 4


def test_grounding_response_map_is_the_configured_grid(tools, settings, vision, water_corner_scene):
    image = load(water_corner_scene, settings)
    context = build_context([image], settings, vision, target="water")

    result = tools[ToolName.GROUNDING].run(context)
    grid = np.array(result.data["response_map"])
    assert grid.shape == (32, 32)
    # The water corner must outscore the opposite corner.
    assert grid[:8, :8].mean() > grid[-8:, -8:].mean()


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def test_counting_builds_on_grounding_and_cross_checks_vqa(tools, settings, vision, water_corner_scene):
    image = load(water_corner_scene, settings)
    context = build_context(
        [image], settings, vision, query="how many water bodies", target="water"
    )

    result = tools[ToolName.COUNTING].run(context)

    assert result.ok
    assert result.data["region_count"] >= 1
    assert result.data["vqa_numeric_answer"] == 3  # the double answers "three"
    assert "lower bound" in result.summary


def test_counting_reports_absence_without_a_fabricated_number(tools, settings, vision):
    image = load(make_scene(width=256, height=256), settings)
    context = build_context([image], settings, vision, target="ship")

    result = tools[ToolName.COUNTING].run(context)

    assert result.data["region_count"] == 0
    assert result.data["present"] is False
    assert "could be localised" in result.summary


def test_counting_without_a_target_is_refused(tools, settings, vision, water_corner_scene):
    image = load(water_corner_scene, settings)
    context = build_context([image], settings, vision, target=None)
    with pytest.raises(QueryError):
        tools[ToolName.COUNTING].run(context)


# ---------------------------------------------------------------------------
# Captioning
# ---------------------------------------------------------------------------


def test_caption_fuses_multiple_real_signals(tools, settings, vision, mixed_scene):
    image = load(mixed_scene, settings)
    context = build_context([image], settings, vision, query="describe this scene")

    result = tools[ToolName.CAPTION].run(context)

    assert result.ok
    assert result.data["path"] == "practical"
    assert result.data["caption_variants"]
    assert result.data["quadrant_captions"]
    assert result.data["texture"]["mean_intensity"] > 0
    assert result.data["scene_label"]
    assert "Texture statistics" in result.summary


def test_caption_prefers_the_strong_backend_when_configured(tools, settings, strong_vision, mixed_scene):
    image = load(mixed_scene, settings)
    context = build_context([image], settings, strong_vision, query="describe this scene")

    result = tools[ToolName.CAPTION].run(context)

    assert result.backend is BackendKind.RSVLM
    assert result.data["path"] == "rsvlm"
    assert "floodplain" in result.summary
    assert "Supporting analysis" in result.summary


def test_caption_for_sar_omits_colour_language(tools, settings, vision):
    image = load(make_sar_scene(), settings, name="sar.png")
    context = build_context([image], settings, vision, query="describe this")

    result = tools[ToolName.CAPTION].run(context)
    assert "backscatter" in result.summary or "radar" in result.summary.lower()
    assert "Dominant tones" not in result.summary


# ---------------------------------------------------------------------------
# VQA
# ---------------------------------------------------------------------------


def test_vqa_cross_checks_a_presence_question(tools, settings, vision, water_corner_scene):
    image = load(water_corner_scene, settings)
    context = build_context(
        [image],
        settings,
        vision,
        query="Is there water in this image?",
        target="water",
        arguments={"question": "Is there water in this image?"},
    )

    result = tools[ToolName.VQA].run(context)

    assert result.ok
    assert result.data["is_yes_no"] is True
    probe = result.data["presence_probe"]
    assert probe is not None
    assert probe["method"].startswith("CLIP")
    assert "CLIP probe" in result.summary


def test_vqa_reports_disagreement_between_the_two_models(tools, settings, embedder, water_corner_scene):
    from satquery.backends.base import VisionSuite
    from conftest import FakeAnswerer, FakeCaptioner

    # Force the language model to deny what the pixels plainly show.
    contrary = VisionSuite(
        embedder=embedder,
        captioner=FakeCaptioner(),
        answerer=FakeAnswerer(forced="no"),
        strong=None,
    )
    image = load(water_corner_scene, settings)
    context = build_context(
        [image],
        settings,
        contrary,
        query="Is there water in this image?",
        target="water",
        arguments={"question": "Is there water in this image?"},
    )

    result = tools[ToolName.VQA].run(context)

    assert result.data["cross_check_agreement"] is False
    assert "disagree" in result.summary


def test_vqa_open_question_returns_a_decode_confidence(tools, settings, vision, mixed_scene):
    image = load(mixed_scene, settings)
    context = build_context(
        [image],
        settings,
        vision,
        query="What is the dominant land cover?",
        arguments={"question": "What is the dominant land cover?"},
    )

    result = tools[ToolName.VQA].run(context)

    assert result.data["is_yes_no"] is False
    assert result.data["presence_probe"] is None
    assert result.data["decode_score"] is not None


def test_vqa_flags_colour_questions_on_radar_imagery(tools, settings, vision):
    image = load(make_sar_scene(), settings, name="sar.png")
    context = build_context(
        [image],
        settings,
        vision,
        query="What colour is the field?",
        arguments={"question": "What colour is the field?"},
    )

    result = tools[ToolName.VQA].run(context)
    assert "radar image" in result.summary


def test_vqa_uses_the_strong_backend_when_available(tools, settings, strong_vision, mixed_scene):
    image = load(mixed_scene, settings)
    context = build_context(
        [image],
        settings,
        strong_vision,
        query="What is here?",
        arguments={"question": "What is here?"},
    )

    result = tools[ToolName.VQA].run(context)
    assert result.backend is BackendKind.RSVLM


# ---------------------------------------------------------------------------
# Change detection
# ---------------------------------------------------------------------------


def test_change_detection_requires_two_epochs(tools, settings, vision, water_corner_scene):
    image = load(water_corner_scene, settings)
    context = build_context([image], settings, vision)

    with pytest.raises(QueryError) as excinfo:
        tools[ToolName.CHANGE].validate(context)
    assert "at least 2" in excinfo.value.message
    assert any("oldest first" in line for line in excinfo.value.remediation)


def test_change_detection_localises_a_new_built_area(tools, settings, vision):
    before = load(make_scene(vegetation_box=(0, 0, 384, 384)), settings, name="t1.png")
    after = load(
        make_scene(vegetation_box=(0, 0, 384, 384), urban_box=(20, 20, 170, 170)),
        settings,
        name="t2.png",
    )
    context = build_context([before, after], settings, vision, query="what changed")

    result = tools[ToolName.CHANGE].run(context)

    assert result.ok
    assert result.data["fused"]["changed_ratio"] > 0.0
    assert result.regions, "expected a change region over the new built area"

    leader = result.regions[0]
    assert leader.centroid[0] < 0.6 and leader.centroid[1] < 0.6
    assert result.data["semantic"]["available"] is True


def test_change_detection_is_quiet_when_only_brightness_shifts(tools, settings, vision):
    import numpy as np
    from PIL import Image

    base = make_scene(width=256, height=256, vegetation_box=(0, 0, 256, 128))
    brighter = Image.fromarray(
        np.clip(np.asarray(base, dtype=np.float64) * 1.2 + 10, 0, 255).astype(np.uint8)
    )

    before = load(base, settings, name="t1.png")
    after = load(brighter, settings, name="t2.png")
    context = build_context([before, after], settings, vision, query="what changed")

    result = tools[ToolName.CHANGE].run(context)

    assert result.data["radiometric"]["mean_difference"] < 0.2
    assert result.data["fused"]["changed_ratio"] < 0.35


def test_change_detection_names_the_land_use_transition(tools, settings, vision):
    before = load(make_scene(vegetation_box=(0, 0, 384, 384)), settings, name="t1.png")
    after = load(make_scene(urban_box=(0, 0, 384, 384)), settings, name="t2.png")
    context = build_context([before, after], settings, vision)

    result = tools[ToolName.CHANGE].run(context)

    transition = result.data["scene_transition"]
    assert transition is not None
    assert transition["before"]["label"]
    assert transition["after"]["label"]


def test_change_detection_warns_about_mismatched_footprints(tools, settings, vision):
    before = load(make_scene(width=384, height=200), settings, name="t1.png")
    after = load(make_scene(width=200, height=384), settings, name="t2.png")
    context = build_context([before, after], settings, vision)

    tools[ToolName.CHANGE].run(context)

    assert any("aspect ratio" in warning for warning in context.warnings)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def test_result_cache_evicts_least_recently_used():
    cache = ResultCache(maxsize=2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")
    cache.put("c", 3)

    assert cache.get("a") == 1
    assert cache.get("b") is None
    assert cache.get("c") == 3


def test_result_cache_can_be_disabled():
    cache = ResultCache(maxsize=0)
    cache.put("a", 1)
    assert cache.get("a") is None


def test_change_detection_significance_gate_is_explicit(tools, settings, vision):
    scene = make_scene(width=256, height=256, vegetation_box=(0, 0, 256, 128))
    before = load(scene, settings, name="t1.png")
    after = load(scene, settings, name="t2.png")
    context = build_context([before, after], settings, vision)

    result = tools[ToolName.CHANGE].run(context)

    assert result.data["fused"]["significant"] is False
    assert result.regions == []
    assert "nothing" in result.summary.lower()


def test_semantic_channel_catches_change_the_radiometric_one_misses(tools, settings, vision):
    # Uniform vegetation to uniform built-up: standardising luma removes the
    # global shift, so pixel differencing sees nothing. Only the semantic
    # channel can flag this, which is exactly why both are computed.
    before = load(make_scene(vegetation_box=(0, 0, 384, 384)), settings, name="t1.png")
    after = load(make_scene(urban_box=(0, 0, 384, 384)), settings, name="t2.png")
    context = build_context([before, after], settings, vision)

    result = tools[ToolName.CHANGE].run(context)

    assert result.data["radiometric"]["mean_difference"] < 0.05
    assert result.data["semantic"]["max_drift"] > 0.15
    assert result.data["fused"]["significant"] is True
    assert result.data["fused"]["changed_ratio"] > 0.5
