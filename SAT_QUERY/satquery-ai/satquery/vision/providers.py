"""Lazy optional model-provider contracts.

No heavyweight detector or segmenter is loaded by default. Grounding DINO and
SAM2 are documented adapters selected only when configured with checkpoints.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Sequence

import numpy as np
from PIL import Image

from .evidence import Detection, Segmentation


class Detector(ABC):
    model_id: str
    model_version: str | None = None

    @abstractmethod
    def detect(self, image: Image.Image, labels: Sequence[str]) -> list[Detection]:
        raise NotImplementedError


class Segmenter(ABC):
    model_id: str
    model_version: str | None = None

    @abstractmethod
    def segment(self, image: Image.Image, boxes: Sequence[tuple[float, float, float, float]] | None = None) -> list[Segmentation]:
        raise NotImplementedError


class GroundingDinoDetector(Detector):
    """Optional Transformers Grounding DINO adapter."""

    def __init__(self, model_id: str = "IDEA-Research/grounding-dino-tiny", *, device: str = "cpu") -> None:
        self.model_id = model_id
        self.device = device
        self._processor = None
        self._model = None

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
        except ImportError as exc:
            raise RuntimeError("Grounding DINO requires transformers and torch.") from exc
        self._processor = AutoProcessor.from_pretrained(self.model_id)
        self._model = AutoModelForZeroShotObjectDetection.from_pretrained(self.model_id).to(self.device).eval()

    def detect(self, image: Image.Image, labels: Sequence[str]) -> list[Detection]:
        self._load()
        import torch
        prompts = [". ".join(labels) + "."]
        inputs = self._processor(images=image, text=prompts, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self._model(**inputs)
        result = self._processor.post_process_grounded_object_detection(
            outputs, input_ids=inputs.get("input_ids"), threshold=0.25, text_threshold=0.25, target_sizes=[image.size[::-1]], text_labels=[list(labels)]
        )[0]
        detections = []
        for box, score, label in zip(result["boxes"], result["scores"], result.get("text_labels", result.get("labels", []))):
            detections.append(Detection(str(label), float(score), tuple(float(value) for value in box.tolist()), "GroundingDINO", self.model_id))
        return detections


class Sam2Segmenter(Segmenter):
    """Optional Transformers SAM2 box-prompt adapter."""

    def __init__(self, model_id: str = "facebook/sam2.1-hiera-tiny", *, device: str = "cpu") -> None:
        self.model_id = model_id
        self.device = device
        self._processor = None
        self._model = None

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from transformers import Sam2Model, Sam2Processor
        except ImportError as exc:
            raise RuntimeError("SAM2 requires a Transformers build with Sam2Model support.") from exc
        self._processor = Sam2Processor.from_pretrained(self.model_id)
        self._model = Sam2Model.from_pretrained(self.model_id).to(self.device).eval()

    def segment(self, image: Image.Image, boxes: Sequence[tuple[float, float, float, float]] | None = None) -> list[Segmentation]:
        if not boxes:
            raise ValueError("SAM2 segmentation requires box prompts in this adapter.")
        self._load()
        import torch
        pixel_boxes = [[[list(box) for box in boxes]]]
        inputs = self._processor(images=image, input_boxes=pixel_boxes, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self._model(**inputs, multimask_output=False)
        masks = self._processor.post_process_masks(outputs.pred_masks, inputs["original_sizes"])[0]
        results = []
        for index, mask in enumerate(masks):
            results.append(Segmentation("prompted-region", float(outputs.iou_scores[0, index, 0].sigmoid().item()), mask[0].bool().cpu().numpy(), "SAM2", self.model_id))
        return results
