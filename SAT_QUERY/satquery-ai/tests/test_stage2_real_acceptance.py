"""Opt-in real Stage 2 model acceptance tests.

Enable explicitly with SATQUERY_RUN_REAL_STAGE2=1. Normal CI never downloads
large checkpoints.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

from satquery.vision import GroundingDinoDetector, Sam2Segmenter, render_evidence

RUN_REAL = os.getenv("SATQUERY_RUN_REAL_STAGE2", "0").lower() in {"1", "true", "yes"}
ROOT = Path(__file__).resolve().parents[1]
IMAGE_PATH = sorted((ROOT / "data" / "fetched_images").glob("*.jpg"))[0]


@pytest.mark.real_stage2
@pytest.mark.skipif(not RUN_REAL, reason="Set SATQUERY_RUN_REAL_STAGE2=1 to download/run real Stage 2 models.")
def test_real_detector_and_segmenter_produce_evidence(tmp_path):
    image = Image.open(IMAGE_PATH).convert("RGB")
    detections = GroundingDinoDetector().detect(image, ["building", "water"])
    assert detections
    masks = Sam2Segmenter().segment(image, [item.box for item in detections[:1]])
    assert masks and masks[0].mask.any()
    output = render_evidence(image, detections=detections, segmentations=masks, output_path=tmp_path / "evidence.jpg")
    assert output.size == image.size
    assert (tmp_path / "evidence.jpg").is_file()
