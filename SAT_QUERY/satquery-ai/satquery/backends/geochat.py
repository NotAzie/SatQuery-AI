"""Optional adapter for an externally installed GeoChat checkpoint."""

from __future__ import annotations

import importlib.util
import importlib
import os
import sys
import tempfile
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional, Sequence, Tuple

from PIL import Image

from ..config import Settings
from ..errors import ResourceNotConfiguredError, ToolExecutionError
from ..schemas import BackendKind
from .base import GenerativeBackend

_RUNTIME: Optional[Dict[str, Any]] = None
_RUNTIME_LOCK = Lock()


class GeoChatVision(GenerativeBackend):
    """Bridge GeoChat's path-based API into SatQuery's image backend contract."""

    kind = BackendKind.RSVLM

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def name(self) -> str:
        return f"geochat:{self.settings.rsvlm_path}"

    def available(self) -> Tuple[bool, Optional[str]]:
        source = self.settings.geochat_source_path
        model = self.settings.rsvlm_path
        if not source or not Path(source).is_dir():
            return False, "SATQUERY_GEOCHAT_SOURCE_PATH is not a valid directory"
        if not model or not Path(model).expanduser().exists():
            return False, "SATQUERY_RSVLM_PATH does not point to a GeoChat checkpoint"
        if importlib.util.find_spec("torch") is None:
            return False, "torch is required by GeoChat"
        return True, None

    def generate(
        self,
        images: Sequence[Image.Image],
        prompt: str,
        *,
        max_new_tokens: Optional[int] = None,
    ) -> str:
        if not images:
            raise ToolExecutionError("geochat", "GeoChat was called without an image.")

        runtime = self._runtime()
        descriptor, image_path = tempfile.mkstemp(suffix=".png")
        os.close(descriptor)
        try:
            images[0].save(image_path, format="PNG")
            chat = runtime["chat_class"](
                runtime["model"], runtime["image_processor"],
                runtime["tokenizer"], runtime["device"]
            )
            conversation = runtime["conversation"].copy()
            image_tokens: list[object] = [image_path]
            chat.upload_img(image_path, conversation, image_tokens)
            chat.ask(prompt, conversation)
            chat.encode_img(image_tokens)
            generation = chat.answer_prepare(
                conversation,
                image_tokens,
                max_new_tokens=max_new_tokens or self.settings.rsvlm_max_new_tokens,
                temperature=self.settings.rsvlm_temperature,
                max_length=2000,
            )

            torch = runtime["torch"]
            with torch.inference_mode():
                output_ids = runtime["model"].generate(
                    generation["input_ids"],
                    images=generation["images"],
                    max_new_tokens=generation["max_new_tokens"],
                    stopping_criteria=generation["stopping_criteria"],
                    do_sample=False,
                    use_cache=True,
                )

            prompt_length = generation["input_ids"].shape[1]
            return runtime["tokenizer"].decode(
                output_ids[0, prompt_length:], skip_special_tokens=True
            ).strip()
        finally:
            try:
                Path(image_path).unlink()
            except FileNotFoundError:
                pass

    def _runtime(self) -> Dict[str, Any]:
        global _RUNTIME
        available, reason = self.available()
        if not available:
            raise ResourceNotConfiguredError(
                f"GeoChat is unavailable: {reason}.",
                remediation=[
                    "Install the dependencies required by the external GeoChat checkout.",
                    "Set SATQUERY_GEOCHAT_SOURCE_PATH to that checkout.",
                    "Set SATQUERY_RSVLM_PATH to the downloaded GeoChat checkpoint.",
                ],
            )
        if _RUNTIME is not None:
            return _RUNTIME

        with _RUNTIME_LOCK:
            if _RUNTIME is not None:
                return _RUNTIME
            source_path = self.settings.geochat_source_path
            model_setting = self.settings.rsvlm_path
            if not source_path or not model_setting:
                raise ResourceNotConfiguredError(
                    "GeoChat requires both a source checkout and a checkpoint path."
                )
            source = str(Path(source_path).expanduser().resolve())
            if source not in sys.path:
                sys.path.insert(0, source)
            try:
                import torch
                conversation_module = importlib.import_module("geochat.conversation")
                builder_module = importlib.import_module("geochat.model.builder")
                utils_module = importlib.import_module("geochat.mm_utils")
                Chat = conversation_module.Chat
                conv_templates = conversation_module.conv_templates
                load_pretrained_model = builder_module.load_pretrained_model
                get_model_name_from_path = utils_module.get_model_name_from_path
            except ImportError as exc:
                raise ToolExecutionError(
                    "geochat",
                    f"GeoChat dependencies could not be imported: {exc}",
                    remediation=["Install the pinned dependencies from the GeoChat checkout."],
                ) from exc

            model_path = str(Path(model_setting).expanduser().resolve())
            device = self.settings.device
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            model_base = os.getenv("SATQUERY_GEOCHAT_MODEL_BASE") or None
            model_name = get_model_name_from_path(model_path)
            try:
                tokenizer, model, image_processor, _ = load_pretrained_model(
                    model_path,
                    model_base,
                    model_name,
                    load_8bit=os.getenv("SATQUERY_GEOCHAT_LOAD_8BIT", "0") == "1",
                    load_4bit=os.getenv("SATQUERY_GEOCHAT_LOAD_4BIT", "0") == "1",
                    device=device,
                )
                model.eval()
            except Exception as exc:
                raise ToolExecutionError(
                    "geochat",
                    f"GeoChat checkpoint loading failed: {exc}",
                    remediation=["Check the checkpoint path and its model dependencies."],
                ) from exc

            _RUNTIME = {
                "torch": torch,
                "chat_class": Chat,
                "conversation": conv_templates["llava_v1"].copy(),
                "tokenizer": tokenizer,
                "model": model,
                "image_processor": image_processor,
                "device": device,
            }
            return _RUNTIME