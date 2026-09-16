"""Optional strong backend: a remote-sensing vision-language model.

This is the upgrade path. When a domain checkpoint is configured it takes over
captioning, VQA, and the language half of grounded answers, because a model
trained on overhead imagery uses the right vocabulary - "riverine floodplain",
"informal settlement", "centre-pivot irrigation" - where a general captioner
reaches for street-level words.

The loader deliberately supports several checkpoint families rather than one,
because domain VLMs are published against whatever base architecture their
authors used. Prompt formatting is handled by the checkpoint's own chat
template where it ships one, which is what keeps this generic instead of
hard-wired to a specific release.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image

from ..config import Settings
from ..errors import ToolExecutionError
from ..registry import ModelRegistry, require_torch
from ..schemas import BackendKind
from .base import GenerativeBackend

logger = logging.getLogger("satquery.backends.rsvlm")


class RSVLMVision(GenerativeBackend):
    """Free-text answers from a remote-sensing VLM checkpoint."""

    kind = BackendKind.RSVLM

    def __init__(self, registry: ModelRegistry, settings: Settings) -> None:
        self.registry = registry
        self.settings = settings

    @property
    def name(self) -> str:
        return f"rsvlm:{self.settings.rsvlm_path}"

    def available(self) -> Tuple[bool, Optional[str]]:
        status = self.registry.status()["rsvlm"]
        return bool(status["available"]), status["reason"]

    # ------------------------------------------------------------------

    def generate(
        self,
        images: Sequence[Image.Image],
        prompt: str,
        *,
        max_new_tokens: Optional[int] = None,
    ) -> str:
        if not images:
            raise ToolExecutionError(
                "rsvlm", "The remote-sensing VLM was called without an image."
            )

        torch = require_torch()
        loaded = self.registry.rsvlm()
        model, processor = loaded.model, loaded.processor
        device = loaded.device
        tokens = max_new_tokens or self.settings.rsvlm_max_new_tokens

        inputs = self._build_inputs(processor, list(images), prompt, device, model)

        generate_kwargs: Dict[str, Any] = {"max_new_tokens": tokens}
        if self.settings.rsvlm_temperature > 0.0:
            generate_kwargs.update(
                do_sample=True, temperature=self.settings.rsvlm_temperature, top_p=0.9
            )
        else:
            generate_kwargs.update(do_sample=False, num_beams=3)

        with torch.no_grad():
            try:
                generated = model.generate(**inputs, **generate_kwargs)
            except Exception as exc:
                raise ToolExecutionError(
                    "rsvlm",
                    f"Generation failed on the remote-sensing VLM: {exc}",
                    remediation=[
                        "Large VLMs need substantial VRAM; try SATQUERY_DTYPE=float16 on CUDA.",
                        "Lower SATQUERY_RSVLM_MAX_TOKENS or SATQUERY_MAX_IMAGE_PX.",
                        "Set SATQUERY_RSVLM_ENABLED=false to fall back to the practical path.",
                    ],
                ) from exc

        return self._decode(processor, inputs, generated, prompt)

    # ------------------------------------------------------------------

    def _build_inputs(
        self,
        processor: Any,
        images: List[Image.Image],
        prompt: str,
        device: str,
        model: Any,
    ) -> Dict[str, Any]:
        """Format the prompt using the checkpoint's own conventions.

        Preference order: the processor's chat template if it has one, then a
        plain `<image>`-prefixed string, then image-only conditioning. Each
        fallback is tried in turn so one unusual processor does not take the
        whole backend down.
        """
        text = self._compose_prompt(prompt)

        chat_template = getattr(processor, "apply_chat_template", None)
        if callable(chat_template):
            try:
                conversation = [
                    {
                        "role": "user",
                        "content": [{"type": "image"} for _ in images]
                        + [{"type": "text", "text": text}],
                    }
                ]
                formatted = processor.apply_chat_template(
                    conversation, add_generation_prompt=True
                )
                if isinstance(formatted, str):
                    inputs = processor(images=images, text=formatted, return_tensors="pt")
                    return self._to_device(inputs, device, model)
            except Exception as exc:
                logger.debug("Chat template path unavailable (%s); trying plain prompt.", exc)

        for candidate in ("<image>\n" + text, text):
            try:
                inputs = processor(images=images, text=candidate, return_tensors="pt")
                return self._to_device(inputs, device, model)
            except Exception as exc:
                logger.debug("Processor rejected prompt form (%s).", exc)

        try:
            inputs = processor(images=images, return_tensors="pt")
            return self._to_device(inputs, device, model)
        except Exception as exc:
            raise ToolExecutionError(
                "rsvlm",
                f"The processor for this checkpoint could not build model inputs: {exc}",
                remediation=[
                    "Set SATQUERY_RSVLM_KIND explicitly rather than leaving it on auto.",
                    "Some community checkpoints need SATQUERY_RSVLM_TRUST_REMOTE_CODE=true.",
                ],
            ) from exc

    def _compose_prompt(self, prompt: str) -> str:
        system = self.settings.rsvlm_system_prompt.strip()
        body = prompt.strip()
        return f"{system}\n\n{body}" if system else body

    @staticmethod
    def _to_device(inputs: Any, device: str, model: Any) -> Dict[str, Any]:
        torch = require_torch()
        moved: Dict[str, Any] = {}
        for key, value in dict(inputs).items():
            if hasattr(value, "to"):
                value = value.to(device)
                if key == "pixel_values" and hasattr(value, "dtype"):
                    if value.dtype.is_floating_point:
                        value = value.to(model.dtype)
            moved[key] = value
        del torch
        return moved

    @staticmethod
    def _decode(processor: Any, inputs: Dict[str, Any], generated: Any, prompt: str) -> str:
        """Decode, trimming the echoed prompt that decoder-only models return."""
        input_ids = inputs.get("input_ids")
        sequences = generated

        if input_ids is not None and hasattr(sequences, "shape"):
            prompt_length = int(input_ids.shape[-1])
            if sequences.shape[-1] > prompt_length:
                sequences = sequences[:, prompt_length:]

        decode = getattr(processor, "batch_decode", None)
        if decode is None:
            tokenizer = getattr(processor, "tokenizer", None)
            if tokenizer is None:
                raise ToolExecutionError(
                    "rsvlm", "This processor exposes no way to decode generated tokens."
                )
            decode = tokenizer.batch_decode

        text = decode(sequences, skip_special_tokens=True)[0].strip()

        # Some processors ignore slicing and still echo the prompt.
        for marker in ("ASSISTANT:", "assistant\n", "<|assistant|>", "Answer:"):
            if marker in text:
                text = text.split(marker)[-1].strip()
        if prompt and text.lower().startswith(prompt.strip().lower()):
            text = text[len(prompt.strip()) :].strip()

        return text.strip()
