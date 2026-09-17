from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw


def global_box(box, tile_bounds, union_bounds, canvas_size):
    tx0, ty0, tx1, ty1 = tile_bounds
    ux0, uy0, ux1, uy1 = union_bounds
    width, height = canvas_size
    lon0 = tx0 + (box[0] / 1024.0) * (tx1 - tx0)
    lat0 = ty1 - (box[3] / 1024.0) * (ty1 - ty0)
    lon1 = tx0 + (box[2] / 1024.0) * (tx1 - tx0)
    lat1 = ty1 - (box[1] / 1024.0) * (ty1 - ty0)
    return ((lon0 - ux0) / (ux1 - ux0) * width, (uy1 - lat1) / (uy1 - uy0) * height, (lon1 - ux0) / (ux1 - ux0) * width, (uy1 - lat0) / (uy1 - uy0) * height)


def reconstruct(tiles, union_bounds, output_path: Path, grid_path: Path, boxes=()):
    first = Image.open(tiles[0]["path"]).convert("RGB")
    canvas_width = max(1, len({tile["col"] for tile in tiles}) * first.width)
    canvas_height = max(1, len({tile["row"] for tile in tiles}) * first.height)
    canvas = Image.new("RGB", (canvas_width, canvas_height))
    grid = canvas.copy()
    draw_grid = ImageDraw.Draw(grid)
    for tile in tiles:
        image = Image.open(tile["path"]).convert("RGB")
        box = global_box((0, 0, image.width, image.height), tile["bounds"], union_bounds, (canvas_width, canvas_height))
        canvas.paste(image.resize((max(1, int(box[2]-box[0])), max(1, int(box[3]-box[1])))), (int(box[0]), int(box[1])))
        draw_grid.rectangle(tuple(int(value) for value in box), outline=(255, 200, 0), width=4)
        draw_grid.text((int(box[0])+5, int(box[1])+5), tile["tile_id"], fill=(255, 255, 0))
    for item in boxes:
        draw = ImageDraw.Draw(canvas)
        item_box = item["box"] if isinstance(item, dict) else item.box
        item_label = item["label"] if isinstance(item, dict) else item.label
        item_confidence = item["confidence"] if isinstance(item, dict) else item.confidence
        draw.rectangle(tuple(int(value) for value in item_box), outline=(255, 0, 0), width=3)
        draw.text((int(item_box[0]), int(item_box[1])), f"{item_label} {item_confidence:.2f}", fill=(255, 255, 0))
    canvas.save(output_path)
    grid.save(grid_path)
    return canvas.size
