"""Visual question answering.

BLIP-VQA answers in one or two words, which is often right but rarely
sufficient on its own for an analyst. Two things improve it here:

* Cross-checking. For yes/no presence questions, the generated answer is
  checked against an independent CLIP presence score. Agreement raises
  confidence; disagreement is reported instead of hidden behind a confident
  one-word reply.
* Framing. The short answer is expanded with the scene context that supports
  it, so the user gets a reason rather than a bare token.

With a remote-sensing VLM configured, that model answers directly and the CLIP
check still runs as corroboration.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple, cast

import numpy as np

from ..backends.base import softmax
from ..schemas import BackendKind, Modality, ScoredLabel, ToolName, ToolResult
from ..taxonomy import contrast_set, phrase_for_target
from .base import Tool, ToolContext

YES_TOKENS = {"yes", "yeah", "yep", "true", "correct", "present", "affirmative"}
NO_TOKENS = {"no", "nope", "none", "false", "absent", "negative", "nothing"}

RSVLM_VQA_TEMPLATE = (
    "Answer this question about the remote sensing image. Be specific and base the answer "
    "only on what is visible.\n\nQuestion: {question}"
)


class VQATool(Tool):
    name = ToolName.VQA
    description = (
        "Answers an open natural-language question about the image, cross-checking yes/no "
        "presence answers against an independent CLIP similarity probe."
    )
    min_images = 1
    max_images = 1

    def run(self, context: ToolContext) -> ToolResult:
        started = time.perf_counter()
        question = context.arguments.get("question") or context.query
        image = context.primary

        backend_kind = BackendKind.PRACTICAL
        answerer = context.vision.answerer
        raw_answer: str
        decode_score: Optional[float] = None

        if context.vision.has_strong:
            backend_kind = BackendKind.RSVLM
            try:
                raw_answer = answerer.generate(
                    [image.pil], RSVLM_VQA_TEMPLATE.format(question=question)
                ).strip()
            except Exception as exc:
                if context.vision.practical_answerer is None:
                    raise
                context.warn(
                    f"Strong VQA backend failed ({exc.__class__.__name__}); "
                    "falling back to practical VQA."
                )
                answerer = context.vision.practical_answerer
                backend_kind = BackendKind.PRACTICAL
                answer_method = getattr(answerer, "answer", None)
                if callable(answer_method):
                    raw_answer, decode_score = cast(
                        Tuple[str, Optional[float]],
                        answer_method(image.pil, self._backend_question(context, question)),
                    )
                else:
                    raw_answer = answerer.generate(
                        [image.pil], self._backend_question(context, question)
                    ).strip()
        elif hasattr(answerer, "answer"):
            answer_method = getattr(answerer, "answer", None)
            if callable(answer_method):
                raw_answer, decode_score = cast(
                    Tuple[str, Optional[float]],
                    answer_method(image.pil, self._backend_question(context, question)),
                )
            else:
                raw_answer = answerer.generate([image.pil], question).strip()
        else:
            raw_answer = answerer.generate(
                [image.pil], self._backend_question(context, question)
            ).strip()

        if not raw_answer:
            raw_answer = "the model produced no answer for this question"

        is_yes_no = self._is_yes_no_question(question)
        target = context.target or self._extract_target(question)

        presence: Optional[Dict[str, Any]] = None
        if is_yes_no and target and context.vision.has_embedder:
            presence = self._presence_probe(context, target)

        scene_context: Optional[Dict[str, Any]] = None
        if not is_yes_no and context.vision.has_embedder:
            try:
                scene_result = context.run_tool(ToolName.SCENE)
                if scene_result.labels:
                    scene_context = {
                        "label": scene_result.labels[0].label,
                        "group": scene_result.labels[0].group,
                        "score": scene_result.labels[0].score,
                        "evidence_quality": scene_result.data.get("evidence_quality"),
                    }
            except Exception as exc:
                context.warn(f"Scene evidence did not contribute to VQA ({exc.__class__.__name__}).")

        polarity = self._polarity(raw_answer)
        agreement: Optional[bool] = None
        confidence = decode_score

        if presence is not None and polarity is not None:
            agreement = polarity == presence["present"]
            base = presence["score"] if presence["present"] else 1.0 - presence["score"]
            if agreement:
                confidence = float(min(0.99, 0.5 + 0.5 * base))
            else:
                confidence = float(max(0.1, 0.5 * base))
        elif presence is not None:
            confidence = presence["score"]

        summary = self._compose(
            context=context,
            question=question,
            raw_answer=raw_answer,
            presence=presence,
            polarity=polarity,
            agreement=agreement,
            decode_score=decode_score,
            backend_kind=backend_kind,
            scene_context=scene_context,
        )

        labels: List[ScoredLabel] = []
        if presence is not None:
            labels.append(
                ScoredLabel(
                    label=f"{target} present", score=round(presence["score"], 4), group="clip_probe"
                )
            )

        return self.result(
            summary=summary,
            started=started,
            backend=backend_kind,
            model=answerer.name,
            data={
                "question": question,
                "raw_answer": raw_answer,
                "is_yes_no": is_yes_no,
                "target": target,
                "decode_score": round(decode_score, 4) if decode_score is not None else None,
                "presence_probe": presence,
                "cross_check_agreement": agreement,
                "scene_context": scene_context,
            },
            labels=labels,
            confidence=round(confidence, 4) if confidence is not None else None,
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _backend_question(context: ToolContext, question: str) -> str:
        """Give practical VQA overhead context without changing user wording."""
        if context.primary.modality is Modality.SAR:
            return f"In this overhead SAR radar image, answer this question: {question}"
        return f"In this overhead satellite image, answer this question: {question}"

    # ------------------------------------------------------------------

    @staticmethod
    def _is_yes_no_question(question: str) -> bool:
        text = question.strip().lower()
        starters = (
            "is ", "are ", "does ", "do ", "did ", "can ", "has ", "have ", "was ", "were ",
            "any ", "is there", "are there",
        )
        return text.startswith(starters)

    @staticmethod
    def _extract_target(question: str) -> Optional[str]:
        """Pull the noun phrase a presence question is about."""
        text = question.strip().lower().rstrip("?")
        patterns = (
            r"(?:are|is)\s+there\s+(?:any\s+|a\s+|an\s+|some\s+)?(.+?)(?:\s+in\s+|\s+on\s+|\s+at\s+|$)",
            r"(?:do|does)\s+(?:this|the|it)\s+\w+\s+(?:contain|have|show)\s+(?:any\s+|a\s+|an\s+)?(.+?)$",
            r"(?:can\s+you\s+see|do\s+you\s+see)\s+(?:any\s+|a\s+|an\s+)?(.+?)(?:\s+in\s+|$)",
            r"^(?:any)\s+(.+?)(?:\s+in\s+|\s+visible|$)",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                candidate = match.group(1).strip(" .,")
                candidate = re.sub(r"^(the|a|an|some|any)\s+", "", candidate)
                if candidate:
                    return candidate
        return None

    @staticmethod
    def _polarity(answer: str) -> Optional[bool]:
        """Map a generated answer onto yes/no where it clearly is one."""
        first = re.split(r"[^a-z]+", answer.strip().lower())
        tokens = [token for token in first if token]
        if not tokens:
            return None
        if tokens[0] in YES_TOKENS:
            return True
        if tokens[0] in NO_TOKENS:
            return False
        joined = " ".join(tokens[:4])
        if any(token in YES_TOKENS for token in tokens[:3]):
            return True
        if joined.startswith("there is no") or joined.startswith("there are no"):
            return False
        return None

    @staticmethod
    def _presence_probe(context: ToolContext, target: str) -> Dict[str, Any]:
        """Independent CLIP check for whether the target appears at all.

        Scores the whole image and its quadrants against the target phrase
        versus a contrast set, and keeps the strongest tile: a small object in
        one corner would be diluted by a whole-image embedding.
        """
        embedder = context.vision.embedder
        image = context.primary.pil

        target_phrase = phrase_for_target(target)
        phrases = [target_phrase] + contrast_set(target_phrase)

        width, height = image.size
        mid_x, mid_y = max(width // 2, 1), max(height // 2, 1)
        views = [
            image,
            image.crop((0, 0, mid_x, mid_y)),
            image.crop((mid_x, 0, width, mid_y)),
            image.crop((0, mid_y, mid_x, height)),
            image.crop((mid_x, mid_y, width, height)),
        ]

        logits = embedder.similarity(views, phrases) * embedder.logit_scale()
        probabilities = softmax(logits, axis=1)[:, 0]

        whole = float(probabilities[0])
        best_tile = float(probabilities[1:].max())
        score = float(max(whole, best_tile))

        return {
            "target_phrase": target_phrase,
            "whole_image_score": round(whole, 4),
            "best_tile_score": round(best_tile, 4),
            "score": round(score, 4),
            "present": bool(score >= 0.35),
            "contrast_count": len(phrases) - 1,
            "method": "CLIP whole-image and quadrant scoring against a contrast set",
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _compose(
        *,
        context: ToolContext,
        question: str,
        raw_answer: str,
        presence: Optional[Dict[str, Any]],
        polarity: Optional[bool],
        agreement: Optional[bool],
        decode_score: Optional[float],
        backend_kind: BackendKind,
        scene_context: Optional[Dict[str, Any]],
    ) -> str:
        parts: List[str] = []

        answer = raw_answer.strip()
        if answer and not answer.endswith((".", "!", "?")):
            answer += "."
        parts.append(answer[0].upper() + answer[1:] if answer else "No answer was produced.")

        if presence is not None:
            verdict = "supports" if agreement else "contradicts"
            parts.append(
                f"An independent CLIP probe scores '{presence['target_phrase']}' at "
                f"{presence['score']:.2f} against {presence['contrast_count']} alternatives "
                f"(whole image {presence['whole_image_score']:.2f}, strongest quadrant "
                f"{presence['best_tile_score']:.2f}), which {verdict} that answer."
            )
            if agreement is False:
                parts.append(
                    "The two models disagree, so treat this answer as unresolved. Asking for "
                    "the object's location instead will give a spatial response map you can "
                    "judge directly."
                )

        if decode_score is not None and presence is None:
            parts.append(
                f"Decoder confidence for this answer is {decode_score:.2f}; that is a "
                "sequence likelihood, not a calibrated probability."
            )

        if scene_context is not None:
            parts.append(
                f"Scene evidence provides context: {scene_context['label']} "
                f"({scene_context['score'] * 100:.1f}% zero-shot mass), "
                f"grouped as {scene_context['group']}; evidence is "
                f"{scene_context.get('evidence_quality') or 'unrated'}."
            )

        if context.primary.modality is Modality.SAR:
            lowered = question.lower()
            if any(word in lowered for word in ("colour", "color", "red", "green", "blue")):
                parts.append(
                    "This is a radar image, so colour has no physical meaning in it - the answer "
                    "above describes brightness in a grayscale amplitude product."
                )

        if backend_kind is BackendKind.PRACTICAL:
            parts.append(
                "Answered by the practical BLIP-VQA path. A remote-sensing VLM would use "
                "domain vocabulary more reliably if one is configured."
            )

        return " ".join(parts)
