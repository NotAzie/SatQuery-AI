"""Routing decisions and target extraction."""

from __future__ import annotations

import pytest

from satquery.config import Settings
from satquery.errors import QueryError
from satquery.router import QueryRouter, extract_target, normalise_query
from satquery.schemas import Intent, ToolName


@pytest.fixture
def router() -> QueryRouter:
    return QueryRouter(Settings(router_mode="rules"))


@pytest.mark.parametrize(
    "query,expected",
    [
        ("Describe this scene in detail", Intent.CAPTION),
        ("Give me a caption for this image", Intent.CAPTION),
        ("What do you see here?", Intent.CAPTION),
        ("What land use category is this?", Intent.SCENE_CLASSIFICATION),
        ("Classify the terrain in this tile", Intent.SCENE_CLASSIFICATION),
        ("Where are the buildings?", Intent.GROUNDING),
        ("Locate the storage tanks", Intent.GROUNDING),
        ("Highlight the runway for me", Intent.GROUNDING),
        ("How many ships are docked here?", Intent.COUNTING),
        ("Count the aircraft on the apron", Intent.COUNTING),
        ("Are there any solar panels in this image?", Intent.PRESENCE),
        ("Is this optical or SAR imagery?", Intent.MODALITY_ANALYSIS),
        ("What sensor produced this?", Intent.MODALITY_ANALYSIS),
        ("What colour is the roof of the large building?", Intent.VQA),
    ],
)
def test_rule_routing_covers_the_common_phrasings(router, query, expected):
    plan = router.route(query, image_count=1)
    assert plan.intent is expected
    assert plan.router == "rules"
    assert plan.rationale


def test_change_wording_with_two_images_routes_to_change_detection(router):
    plan = router.route("What changed between these two images?", image_count=2)
    assert plan.intent is Intent.CHANGE_DETECTION
    assert plan.confidence >= 0.9


def test_change_wording_with_one_image_still_routes_but_less_confidently(router):
    plan = router.route("Compare this to the earlier acquisition", image_count=1)
    assert plan.intent is Intent.CHANGE_DETECTION
    assert plan.confidence < 0.9


def test_counting_outranks_locating_when_both_appear(router):
    plan = router.route("How many buildings are there and where are they?", image_count=1)
    assert plan.intent is Intent.COUNTING


def test_forced_tool_bypasses_routing(router):
    plan = router.route(
        "Describe this scene", image_count=1, force_tool=ToolName.GROUNDING
    )
    assert plan.router == "forced"
    assert plan.steps[0].tool is ToolName.GROUNDING
    assert plan.confidence == 1.0


def test_empty_query_is_refused(router):
    with pytest.raises(QueryError):
        router.route("   ", image_count=1)


def test_very_short_query_falls_back_to_caption(router):
    plan = router.route("this image", image_count=1)
    assert plan.intent is Intent.CAPTION
    assert plan.confidence <= 0.6


def test_plan_carries_arguments_for_the_chosen_tool(router):
    plan = router.route("Where are the ships?", image_count=1)
    step = plan.steps[0]
    assert step.tool is ToolName.GROUNDING
    assert step.arguments["target"] == "ship"


def test_vqa_plan_passes_the_question_through(router):
    plan = router.route("What colour is the water?", image_count=1)
    assert plan.steps[0].tool is ToolName.VQA
    assert plan.steps[0].arguments["question"] == "What colour is the water?"


# ---------------------------------------------------------------------------
# Target extraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query,expected",
    [
        ("Where are the buildings?", "building"),
        ("Locate the ships in the harbour", "ship"),
        ("How many aircraft can you see?", "aircraft"),
        ("Are there any solar panels here?", "solar panel"),
        ("Find the bridge", "bridge"),
        ("Count the storage tanks", "storage tank"),
    ],
)
def test_known_vocabulary_targets_are_extracted(query, expected):
    assert extract_target(query) == expected


def test_unknown_target_falls_back_to_pattern_extraction():
    target = extract_target("Where are the grain silos?")
    assert target is not None
    assert "silo" in target


def test_target_extraction_returns_none_for_a_plain_description_request():
    assert extract_target("Describe what this image shows") is None


def test_normalise_query_strips_punctuation_and_case():
    assert normalise_query("  Where ARE the Ships?! ") == "where are the ships"


# ---------------------------------------------------------------------------
# LLM consultation
# ---------------------------------------------------------------------------


def test_hybrid_router_consults_the_llm_only_when_rules_are_unsure(monkeypatch):
    settings = Settings(router_mode="hybrid", llm_api_key="sk-test")
    router = QueryRouter(settings)

    calls = []

    def fake_plan(query, *, image_count):
        calls.append(query)
        return {
            "intent": "SCENE_CLASSIFICATION",
            "target": None,
            "rationale": "planner decided",
            "confidence": 0.88,
        }

    monkeypatch.setattr(router._planner, "plan", fake_plan)

    confident = router.route("How many ships are here?", image_count=1)
    assert confident.router == "rules"
    assert calls == []

    ambiguous = router.route(
        "Give me a sense of what this tile is mostly made up of", image_count=1
    )
    assert ambiguous.router == "llm"
    assert ambiguous.intent is Intent.SCENE_CLASSIFICATION
    assert len(calls) == 1


def test_planner_failure_degrades_to_rule_routing(monkeypatch):
    settings = Settings(router_mode="hybrid", llm_api_key="sk-test")
    router = QueryRouter(settings)

    monkeypatch.setattr(
        router._planner, "plan", lambda query, *, image_count: (_ for _ in ()).throw(RuntimeError("down"))
    )

    plan = router.route("Tell me roughly what sort of place this might be", image_count=1)
    assert plan.router == "rules"
    assert plan.intent in set(Intent)


def test_planner_returning_nonsense_degrades_to_rules(monkeypatch):
    settings = Settings(router_mode="hybrid", llm_api_key="sk-test")
    router = QueryRouter(settings)
    monkeypatch.setattr(
        router._planner, "plan", lambda query, *, image_count: {"intent": "TELEPORT"}
    )

    plan = router.route("Something quite unusual about this tile", image_count=1)
    assert plan.router == "rules"


def test_planner_cannot_invent_a_second_epoch(monkeypatch):
    settings = Settings(router_mode="llm", llm_api_key="sk-test")
    router = QueryRouter(settings)
    monkeypatch.setattr(
        router._planner,
        "plan",
        lambda query, *, image_count: {
            "intent": "CHANGE_DETECTION",
            "confidence": 0.99,
            "rationale": "looks comparative",
        },
    )

    plan = router.route("anything at all", image_count=1)
    assert plan.intent is Intent.CHANGE_DETECTION
    assert "only one image" in plan.rationale
