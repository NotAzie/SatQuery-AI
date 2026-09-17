from __future__ import annotations

import numpy as np
import pytest

from satquery.eo.data import from_array
from satquery.vision.evidence import Detection, Segmentation, pixel_box_to_geo
from satquery.vision.measure import count_detections, measure_detections, measure_mask
from satquery.vision.merge import generate_tiles, non_max_suppression


def detection(label="building", confidence=0.8, box=(10.0, 10.0, 30.0, 30.0), tile=None):
    return Detection(label, confidence, box, "test", "test-model", tile_id=tile)


def test_detection_schema_and_confidence():
    item = detection()
    assert item.box == (10.0, 10.0, 30.0, 30.0)
    with pytest.raises(ValueError):
        detection(confidence=1.2)


def test_nms_keeps_highest_overlapping_box():
    result = non_max_suppression([detection(confidence=0.7), detection(confidence=0.9)], iou_threshold=0.5)
    assert len(result) == 1
    assert result[0].confidence == 0.9


def test_tile_generation_covers_edges():
    tiles = generate_tiles(100, 80, tile_size=50, overlap=0.2)
    assert tiles
    assert max(tile.right for tile in tiles) == 100
    assert max(tile.bottom for tile in tiles) == 80


def test_count_and_detection_measurement():
    detections = [detection(), detection("ship", 0.4), detection("building", 0.2)]
    assert count_detections(detections, label="building", minimum_confidence=0.5)["count"] == 1
    result = measure_detections(detections)
    assert result[0]["pixel_area"] == 400.0


def test_mask_measurement_and_geographic_footprint():
    mask = np.zeros((4, 4), dtype=bool)
    mask[1:3, 1:3] = True
    segmentation = Segmentation("water", 0.9, mask, "test", "test-model")
    raster = from_array(np.zeros((1, 4, 4)), crs="EPSG:3857", transform=(10, 0, 0, 0, -10, 40), bounds=(0, 0, 40, 40))
    measurement = measure_mask(segmentation, raster)
    assert measurement["pixel_count"] == 4
    assert measurement["area_m2"] == pytest.approx(400.0)
    footprint = pixel_box_to_geo((1, 1, 3, 3), raster)
    assert footprint is not None
    assert footprint.crs == "EPSG:3857"


def test_non_georeferenced_input_never_gets_geo_coordinates():
    mask = np.ones((3, 3), dtype=bool)
    segmentation = Segmentation("water", 0.8, mask, "test", "test-model")
    assert pixel_box_to_geo((0, 0, 3, 3), from_array(np.zeros((1, 3, 3)))) is None
    assert measure_mask(segmentation)["area_available"] is False
