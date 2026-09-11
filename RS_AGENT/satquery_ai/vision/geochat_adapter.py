"""Lazy adapter for an externally installed GeoChat checkpoint.

SatQuery owns this adapter; the upstream GeoChat source and model remain external
dependencies and are not copied, renamed, or modified in this repository.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from threading import Lock
from typing import Any

_runtime: dict[str, Any] | None = None
_runtime_lock = Lock()


def _configuration_message() -> str:
    return (
        "GeoChat vision is not configured. Set GEOCHAT_SOURCE_PATH to an installed "
        "GeoChat checkout and GEOCHAT_MODEL_PATH to its downloaded checkpoint."
    )


def _load_runtime() -> dict[str, Any] | None:
    global _runtime
    if _runtime is not None:
        return _runtime

    source_path = os.getenv("GEOCHAT_SOURCE_PATH")
    model_path = os.getenv("GEOCHAT_MODEL_PATH")
    if not source_path or not model_path:
        return None
    source = Path(source_path).expanduser().resolve()
    if not source.is_dir() or not Path(model_path).expanduser().exists():
        return None

    with _runtime_lock:
        if _runtime is not None:
            return _runtime
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))
        try:
            import torch
            from PIL import Image
            from geochat.conversation import Chat, conv_templates
            from geochat.model.builder import load_pretrained_model
            from geochat.mm_utils import get_model_name_from_path
        except ImportError as exc:
            raise RuntimeError(
                "GeoChat is configured but its runtime dependencies are unavailable. "
                "Install the pinned dependencies from the external GeoChat checkout."
            ) from exc

        device = os.getenv("GEOCHAT_DEVICE", "cuda")
        model_base = os.getenv("GEOCHAT_MODEL_BASE") or None
        model_path = str(Path(model_path).expanduser().resolve())
        model_name = get_model_name_from_path(model_path)
        tokenizer, model, image_processor, _ = load_pretrained_model(
            model_path, model_base, model_name,
            load_8bit=os.getenv("GEOCHAT_LOAD_8BIT", "0") == "1",
            load_4bit=os.getenv("GEOCHAT_LOAD_4BIT", "0") == "1",
            device=device,
        )
        model.eval()
        _runtime = {
            "torch": torch,
            "Image": Image,
            "chat_class": Chat,
            "conversation": conv_templates["llava_v1"].copy(),
            "tokenizer": tokenizer,
            "model": model,
            "image_processor": image_processor,
            "device": device,
        }
        return _runtime


def _run(image_path: str, question: str) -> str:
    image = Path(image_path)
    if not image.is_file():
        raise FileNotFoundError(f"Image not found: {image}")
    runtime = _load_runtime()
    if runtime is None:
        return _configuration_message()

    chat = runtime["chat_class"](
        runtime["model"], runtime["image_processor"], runtime["tokenizer"], runtime["device"]
    )
    conversation = runtime["conversation"].copy()
    images: list[object] = [str(image)]
    chat.upload_img(str(image), conversation, images)
    chat.ask(question, conversation)
    chat.encode_img(images)
    generation = chat.answer_prepare(
        conversation, images, max_new_tokens=300, temperature=0.2, max_length=2000
    )
    with runtime["torch"].inference_mode():
        output_ids = runtime["model"].generate(
            generation["input_ids"],
            images=generation["images"],
            max_new_tokens=generation["max_new_tokens"],
            stopping_criteria=generation["stopping_criteria"],
            do_sample=False,
            use_cache=True,
        )
    prompt_length = generation["input_ids"].shape[1]
    return runtime["tokenizer"].decode(output_ids[0, prompt_length:], skip_special_tokens=True).strip()


def geochat_vqa(image_path: str, question: str | None = None) -> str:
    """Answer a visual question using the configured remote-sensing VLM."""
    return _run(image_path, question or "What is shown in this image?")


def geochat_caption(image_path: str) -> str:
    """Generate a remote-sensing caption using the configured vision-language model."""
    return _run(image_path, "Describe this remote-sensing image concisely.")


def geochat_scene(image_path: str, question: str | None = None) -> str:
    """Classify a scene using the configured remote-sensing VLM."""
    return _run(image_path, question or "Classify the scene in this image in one short phrase.")


def geochat_grounding(image_path: str, question: str | None = None) -> str:
    """Return GeoChat's text-plus-region grounding response for an image query."""
    prompt = question or "Describe the important objects and their locations."
    return _run(image_path, f"[grounding] {prompt}")