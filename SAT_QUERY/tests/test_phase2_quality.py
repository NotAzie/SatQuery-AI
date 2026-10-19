"""Phase 2 quality regressions for the four core vision tools."""

from __future__ import annotations

import pytest

from satquery.schemas import ToolName
from satquery.tools import build_tools

from test_tools import build_context, load


@pytest.fixture
def tools():
    return build_tools()


def test_caption_uses_remote_sensing_prompt_ensemble(tools, settings, vision, mixed_scene):
    image = load(mixed_scene, settings)
    context = build_context([image], settings, vision, query="describe this scene")

    result = tools[ToolName.CAPTION].run(context)

    prompts = vision.captioner.calls
    assert any("satellite" in prompt.lower() or "land-use" in prompt.lower() for prompt in prompts)
    assert "remote-sensing evidence" in result.summary.lower()


def test_practical_vqa_receives_overhead_context(tools, settings, vision, mixed_scene):
    image = load(mixed_scene, settings)
    context = build_context(
        [image],
        settings,
        vision,
        query="What is the dominant land cover?",
        arguments={"question": "What is the dominant land cover?"},
    )

    result = tools[ToolName.VQA].run(context)

    assert result.ok
    assert vision.answerer.questions
    assert "overhead satellite image" in vision.answerer.questions[-1].lower()
    assert result.data["question"] == "What is the dominant land cover?"


def test_scene_reports_label_margin_and_tile_support(tools, settings, vision, mixed_scene):
    image = load(mixed_scene, settings)
    context = build_context([image], settings, vision, query="what land use is this")

    result = tools[ToolName.SCENE].run(context)

    assert 0.0 <= result.data["top_label_margin"] <= 1.0
    assert 0.0 <= result.data["top_label_tile_support"] <= 1.0
    assert result.data["evidence_quality"] in {"stable", "mixed"}
    assert "evidence stability" in result.summary.lower()


def test_grounding_reports_cross_window_support(tools, settings, vision, water_corner_scene):
    image = load(water_corner_scene, settings)
    context = build_context([image], settings, vision, target="water")

    result = tools[ToolName.GROUNDING].run(context)

    assert result.data["window_score_std"] >= 0.0
    assert result.data["strong_window_count"] > 0
    assert 0.0 < result.data["window_support_fraction"] <= 1.0
    assert result.data["window_support_fraction"] == pytest.approx(
        result.data["strong_window_count"] / result.data["windows_scored"], abs=1e-4
    )


def test_grounding_uses_overhead_target_ensemble(tools, settings, vision, water_corner_scene):
    image = load(water_corner_scene, settings)
    context = build_context([image], settings, vision, target="water")

    result = tools[ToolName.GROUNDING].run(context)

    assert len(result.data["target_variants"]) == 3
    assert result.data["target_variants"][0] == result.data["target_phrase"]


def test_open_vqa_includes_scene_evidence(tools, settings, vision, mixed_scene):
    image = load(mixed_scene, settings)
    context = build_context(
        [image],
        settings,
        vision,
        query="What do you see in this image?",
        arguments={"question": "What do you see in this image?"},
    )

    result = tools[ToolName.VQA].run(context)

    assert result.data["scene_context"] is not None
    assert "scene evidence provides context" in result.summary.lower()
