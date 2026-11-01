"""Image ingestion and pure-pixel analysis."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from satquery.config import Settings
from satquery.errors import ImageError, ImageNotFoundError
from satquery.imaging import (
    accumulate_window_scores,
    align_pair,
    analyse_modality,
    apply_modality,
    box_blur,
    connected_components,
    describe_placement,
    dominant_colour_terms,
    generate_windows,
    load_image_from_bytes,
    load_image_from_path,
    normalised_difference,
    otsu_threshold,
    patch_grid,
    regions_from_score_map,
    to_gray,
)
from satquery.schemas import Modality

from conftest import make_sar_scene, make_scene, to_png_bytes


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_load_from_bytes_normalises_to_rgb(settings):
    payload = to_png_bytes(make_scene(width=200, height=160))
    loaded = load_image_from_bytes(payload, "scene.png", settings)

    assert loaded.array.shape == (160, 200, 3)
    assert loaded.array.dtype == np.uint8
    assert loaded.width == 200 and loaded.height == 160
    assert len(loaded.sha256) == 64
    assert loaded.was_resized is False


def test_grayscale_input_becomes_three_channel(settings):
    gray = Image.fromarray(np.full((120, 120), 90, dtype=np.uint8), mode="L")
    loaded = load_image_from_bytes(to_png_bytes(gray), "band.png", settings)
    assert loaded.array.shape[2] == 3
    assert loaded.original_mode == "L"


def test_sixteen_bit_input_is_percentile_stretched(settings):
    raw = np.linspace(0, 40000, 128 * 128).reshape(128, 128).astype(np.uint16)
    image = Image.fromarray(raw, mode="I;16")
    loaded = load_image_from_bytes(to_png_bytes(image), "dn.png", settings)

    assert loaded.array.dtype == np.uint8
    # A linear ramp should end up spanning most of the 8-bit range.
    assert int(loaded.array.max()) - int(loaded.array.min()) > 200


def test_oversized_image_is_downsampled_to_the_configured_limit(settings):
    payload = to_png_bytes(make_scene(width=900, height=700))
    loaded = load_image_from_bytes(payload, "big.png", settings)

    assert max(loaded.width, loaded.height) == settings.max_image_pixels
    assert loaded.was_resized is True
    assert loaded.original_size == (900, 700)


def test_empty_payload_is_rejected(settings):
    with pytest.raises(ImageError) as excinfo:
        load_image_from_bytes(b"", "empty.png", settings)
    assert "empty" in excinfo.value.message.lower()


def test_non_image_payload_is_rejected_with_guidance(settings):
    with pytest.raises(ImageError) as excinfo:
        load_image_from_bytes(b"this is not an image at all", "notes.txt", settings)
    assert excinfo.value.remediation


def test_upload_over_size_limit_is_rejected():
    settings = Settings(max_upload_mb=0.001)
    payload = to_png_bytes(make_scene(width=400, height=400))
    with pytest.raises(ImageError) as excinfo:
        load_image_from_bytes(payload, "heavy.png", settings)
    assert "MB" in excinfo.value.message


def test_tiny_image_is_rejected(settings):
    tiny = Image.fromarray(np.zeros((16, 16, 3), dtype=np.uint8), mode="RGB")
    with pytest.raises(ImageError):
        load_image_from_bytes(to_png_bytes(tiny), "tiny.png", settings)


def test_load_from_path_inside_the_sandbox(tmp_path):
    settings = Settings(image_root=str(tmp_path), max_image_pixels=384)
    target = tmp_path / "scene.png"
    target.write_bytes(to_png_bytes(make_scene(width=120, height=120)))

    loaded = load_image_from_path("scene.png", settings)
    assert loaded.filename == "scene.png"
    assert loaded.source.endswith("scene.png")


def test_path_escaping_the_sandbox_is_refused(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(to_png_bytes(make_scene(width=64, height=64)))

    settings = Settings(image_root=str(root))
    with pytest.raises(ImageError) as excinfo:
        load_image_from_path("../secret.png", settings)
    assert "outside" in excinfo.value.message


def test_missing_path_raises_not_found(tmp_path):
    settings = Settings(image_root=str(tmp_path))
    with pytest.raises(ImageNotFoundError):
        load_image_from_path("absent.png", settings)


def test_path_access_can_be_disabled():
    settings = Settings(allow_image_paths=False)
    with pytest.raises(ImageError) as excinfo:
        load_image_from_path("/tmp/whatever.png", settings)
    assert "disabled" in excinfo.value.message


def test_unsupported_extension_is_refused(tmp_path):
    settings = Settings(image_root=str(tmp_path))
    target = tmp_path / "scene.raw"
    target.write_bytes(b"\x00\x01\x02")
    with pytest.raises(ImageError) as excinfo:
        load_image_from_path("scene.raw", settings)
    assert "extension" in excinfo.value.message


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def test_box_blur_preserves_a_constant_field():
    field = np.full((32, 32), 4.0)
    assert np.allclose(box_blur(field, radius=3), 4.0)


def test_box_blur_smooths_an_impulse():
    field = np.zeros((21, 21))
    field[10, 10] = 100.0
    blurred = box_blur(field, radius=2)
    assert blurred[10, 10] < 100.0
    assert blurred[10, 11] > 0.0
    assert np.isclose(blurred.sum(), field.sum(), rtol=0.05)


def test_otsu_separates_a_bimodal_distribution():
    values = np.concatenate([np.full(500, 10.0), np.full(500, 200.0)])
    threshold = otsu_threshold(values)
    assert 10.0 < threshold < 200.0


def test_otsu_on_a_constant_field_is_stable():
    assert otsu_threshold(np.full(100, 7.0)) == pytest.approx(7.0)


def test_connected_components_separates_disjoint_blobs():
    mask = np.zeros((10, 10), dtype=bool)
    mask[1:3, 1:3] = True
    mask[7:9, 7:9] = True
    components = connected_components(mask)
    assert len(components) == 2
    assert all(component.shape[0] == 4 for component in components)


def test_connected_components_joins_touching_cells():
    mask = np.zeros((6, 6), dtype=bool)
    mask[2, 1:5] = True
    mask[3, 4] = True
    assert len(connected_components(mask)) == 1


def test_connected_components_on_an_empty_mask():
    assert connected_components(np.zeros((5, 5), dtype=bool)) == []


def test_describe_placement_covers_the_grid():
    assert describe_placement(0.1, 0.1) == "top-left of the scene"
    assert describe_placement(0.5, 0.5) == "centre of the scene"
    assert describe_placement(0.9, 0.9) == "bottom-right of the scene"
    assert describe_placement(0.5, 0.1) == "top of the scene"


def test_regions_from_score_map_boxes_the_hot_corner():
    score_map = np.zeros((16, 16))
    score_map[0:4, 0:4] = 0.9

    regions = regions_from_score_map(
        score_map,
        label="water",
        width=320,
        height=320,
        threshold=0.5,
        min_area_fraction=0.001,
        max_regions=5,
    )

    assert len(regions) == 1
    region = regions[0]
    assert region.label == "water"
    assert region.box.x0 < 0.1 and region.box.y0 < 0.1
    assert region.box.x1 < 0.45 and region.box.y1 < 0.45
    assert region.placement == "top-left of the scene"
    assert region.box.pixel_box[0] == 0


def test_regions_below_minimum_area_are_dropped():
    score_map = np.zeros((32, 32))
    score_map[0, 0] = 1.0
    regions = regions_from_score_map(
        score_map,
        label="speck",
        width=100,
        height=100,
        threshold=0.5,
        min_area_fraction=0.05,
        max_regions=5,
    )
    assert regions == []


def test_regions_are_ranked_by_peak_and_capped():
    score_map = np.zeros((20, 20))
    score_map[0:3, 0:3] = 0.6
    score_map[10:13, 10:13] = 0.95
    score_map[17:20, 0:3] = 0.75

    regions = regions_from_score_map(
        score_map,
        label="x",
        width=200,
        height=200,
        threshold=0.5,
        min_area_fraction=0.001,
        max_regions=2,
    )
    assert len(regions) == 2
    assert regions[0].score >= regions[1].score
    assert regions[0].region_id == "reg-001"


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------


def test_generate_windows_respects_the_budget():
    windows = generate_windows(512, 512, (0.5, 0.3, 0.2, 0.1), max_windows=40)
    assert 0 < len(windows) <= 40
    assert all(window.right <= 512 and window.bottom <= 512 for window in windows)
    assert all(window.right > window.left for window in windows)


def test_generate_windows_covers_the_far_edges():
    windows = generate_windows(300, 200, (0.5,), stride_ratio=0.5, max_windows=100)
    assert max(window.right for window in windows) == 300
    assert max(window.bottom for window in windows) == 200


def test_generate_windows_always_returns_something_for_tiny_images():
    windows = generate_windows(40, 40, (0.5, 0.25))
    assert len(windows) >= 1


def test_accumulate_window_scores_localises_the_hot_window():
    windows = generate_windows(256, 256, (0.5,), stride_ratio=0.5, max_windows=16)
    scores = [1.0 if (window.left == 0 and window.top == 0) else 0.0 for window in windows]

    grid = accumulate_window_scores(windows, scores, 256, 256, grid=16)
    assert grid.shape == (16, 16)
    assert grid[0, 0] > grid[-1, -1]


def test_accumulate_rejects_mismatched_lengths():
    windows = generate_windows(128, 128, (0.5,), max_windows=4)
    with pytest.raises(ValueError):
        accumulate_window_scores(windows, [1.0], 128, 128)


def test_patch_grid_tiles_the_whole_image():
    image = make_scene(width=128, height=128)
    crops, coords = patch_grid(image, 4)
    assert len(crops) == 16 and len(coords) == 16
    assert coords[0] == (0, 0) and coords[-1] == (3, 3)
    assert all(crop.size[0] > 0 and crop.size[1] > 0 for crop in crops)


# ---------------------------------------------------------------------------
# Modality
# ---------------------------------------------------------------------------


def test_optical_scene_is_recognised_as_optical():
    array = np.asarray(make_scene(water_box=(0, 0, 150, 150)), dtype=np.uint8)
    modality, confidence, evidence = analyse_modality(array)
    assert modality is Modality.OPTICAL
    assert confidence > 0.5
    assert evidence["mean_channel_spread"] > 20


def test_speckled_grayscale_scene_is_recognised_as_sar():
    array = np.asarray(make_sar_scene(), dtype=np.uint8)
    modality, confidence, evidence = analyse_modality(array)
    assert modality is Modality.SAR
    assert evidence["mean_channel_spread"] < 5
    assert evidence["median_local_coefficient_of_variation"] > 0.12


def test_explicit_hint_overrides_the_heuristic(settings):
    payload = to_png_bytes(make_scene())
    loaded = load_image_from_bytes(payload, "optical.png", settings)
    applied = apply_modality(loaded, Modality.SAR)

    assert applied.modality is Modality.SAR
    assert applied.modality_confidence == 1.0
    assert applied.modality_evidence["overridden_by_hint"] is True
    assert applied.modality_evidence["heuristic_modality"] == Modality.OPTICAL.value


def test_dominant_colour_terms_report_real_fractions():
    array = np.asarray(make_scene(vegetation_box=(0, 0, 384, 200)), dtype=np.uint8)
    terms = dominant_colour_terms(array)
    assert any("vegetat" in term for term in terms)


# ---------------------------------------------------------------------------
# Change detection support
# ---------------------------------------------------------------------------


def test_align_pair_resamples_to_a_common_raster(settings):
    first = load_image_from_bytes(to_png_bytes(make_scene(width=300, height=300)), "a.png", settings)
    second = load_image_from_bytes(to_png_bytes(make_scene(width=220, height=220)), "b.png", settings)

    array_a, array_b, size, warnings = align_pair(first, second)
    assert array_a.shape == array_b.shape
    assert size == (220, 220)
    assert any("resampled" in warning for warning in warnings)


def test_normalised_difference_ignores_a_global_gain_shift():
    base = np.asarray(make_scene(width=128, height=128), dtype=np.uint8)
    brighter = np.clip(base.astype(np.float64) * 1.25 + 12, 0, 255).astype(np.uint8)

    difference = normalised_difference(base, brighter)
    assert float(difference.mean()) < 0.15


def test_normalised_difference_flags_real_structural_change():
    before = np.asarray(make_scene(width=128, height=128), dtype=np.uint8)
    after = np.asarray(
        make_scene(width=128, height=128, urban_box=(0, 0, 70, 70)), dtype=np.uint8
    )

    difference = normalised_difference(before, after)
    assert float(difference[:60, :60].mean()) > float(difference[90:, 90:].mean())


def test_to_gray_matches_bt601_weights():
    pixel = np.array([[[255, 0, 0]]], dtype=np.uint8)
    assert to_gray(pixel)[0, 0] == pytest.approx(0.299 * 255, rel=1e-6)
