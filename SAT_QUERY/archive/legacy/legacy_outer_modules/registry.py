"""Lazy model registry.

Heavy objects are expensive to build and cheap to keep, so every model is
loaded on first use, kept for the lifetime of the process, and guarded by a
per-key lock so that two concurrent requests never build the same model twice.

Nothing in this module imports torch or transformers at module scope. That is
deliberate: `satquery.registry` must import cleanly on a machine with neither
installed, so that the health endpoint can report exactly what is missing
instead of the whole service failing to start.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import Settings
from .errors import DependencyMissingError, ModelLoadError, ResourceNotConfiguredError

logger = logging.getLogger("satquery.registry")


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def probe_dependencies() -> Dict[str, Any]:
    """Report which optional dependencies are importable, and their versions."""
    report: Dict[str, Any] = {}
    for name in ("torch", "transformers", "PIL", "numpy", "httpx", "accelerate", "sentencepiece"):
        if not _has_module(name):
            report[name] = {"installed": False, "version": None}
            continue
        try:
            module = importlib.import_module(name)
            report[name] = {
                "installed": True,
                "version": getattr(module, "__version__", "unknown"),
            }
        except Exception as exc:  # pragma: no cover - broken install
            report[name] = {"installed": False, "version": None, "error": str(exc)}
    return report


def require_torch():
    """Import torch, or raise an error that says how to install it."""
    if not _has_module("torch"):
        raise DependencyMissingError.for_package(
            "torch",
            "running vision models",
            "pip install torch --index-url https://download.pytorch.org/whl/cpu   "
            "(or the CUDA wheel matching your driver)",
        )
    return importlib.import_module("torch")


def require_transformers():
    """Import transformers, or raise an error that says how to install it."""
    if not _has_module("transformers"):
        raise DependencyMissingError.for_package(
            "transformers",
            "loading BLIP, CLIP, and remote-sensing VLM checkpoints",
            "pip install transformers",
        )
    return importlib.import_module("transformers")


@dataclass(frozen=True)
class LoadedModel:
    """A model plus its processor and the metadata the trace wants."""

    key: str
    model: Any
    processor: Any
    model_id: str
    device: str
    dtype: str
    load_seconds: float


class ModelRegistry:
    """Loads and caches every model SatQuery can use."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._models: Dict[str, LoadedModel] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._registry_lock = threading.Lock()
        self._device: Optional[str] = None
        self._dtype_name: Optional[str] = None

    # -- Device / dtype ----------------------------------------------------

    def resolve_device(self) -> str:
        """Pick the compute device once and remember it."""
        if self._device is not None:
            return self._device

        requested = self.settings.device
        if requested != "auto":
            if requested in {"cuda", "mps"}:
                torch = require_torch()
                if requested == "cuda" and not torch.cuda.is_available():
                    raise ResourceNotConfiguredError(
                        "SATQUERY_DEVICE=cuda but torch reports no CUDA device.",
                        remediation=[
                            "Check `nvidia-smi` and that a CUDA-enabled torch build is installed.",
                            "Or set SATQUERY_DEVICE=auto / cpu.",
                        ],
                    )
                if requested == "mps" and not getattr(torch.backends, "mps", None):
                    raise ResourceNotConfiguredError(
                        "SATQUERY_DEVICE=mps but this torch build has no MPS backend.",
                        remediation=["Set SATQUERY_DEVICE=auto or cpu."],
                    )
            self._device = requested
            return self._device

        if _has_module("torch"):
            torch = importlib.import_module("torch")
            if torch.cuda.is_available():
                self._device = "cuda"
            elif getattr(getattr(torch.backends, "mps", None), "is_available", lambda: False)():
                self._device = "mps"
            else:
                self._device = "cpu"
        else:
            self._device = "cpu"
        return self._device

    def resolve_dtype(self):
        """Pick a torch dtype appropriate to the device."""
        torch = require_torch()
        requested = self.settings.dtype
        device = self.resolve_device()

        if requested == "auto":
            # Half precision is a large win on CUDA and a correctness hazard on
            # CPU, where many kernels fall back to slow or unsupported paths.
            name = "float16" if device == "cuda" else "float32"
        else:
            name = requested
            if name in {"float16", "bfloat16"} and device == "cpu":
                logger.warning(
                    "%s on CPU is slow and poorly supported; falling back to float32.", name
                )
                name = "float32"

        self._dtype_name = name
        return getattr(torch, name)

    @property
    def dtype_name(self) -> str:
        return self._dtype_name or (
            "float16" if self.resolve_device() == "cuda" else "float32"
        )

    # -- Generic lazy loader -----------------------------------------------

    def _lock_for(self, key: str) -> threading.Lock:
        with self._registry_lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]

    def _load(self, key: str, builder: Callable[[], Tuple[Any, Any, str]]) -> LoadedModel:
        cached = self._models.get(key)
        if cached is not None:
            return cached

        with self._lock_for(key):
            cached = self._models.get(key)
            if cached is not None:
                return cached

            started = time.perf_counter()
            logger.info("Loading %s ...", key)
            model, processor, model_id = builder()
            elapsed = time.perf_counter() - started

            loaded = LoadedModel(
                key=key,
                model=model,
                processor=processor,
                model_id=model_id,
                device=self.resolve_device(),
                dtype=self.dtype_name,
                load_seconds=round(elapsed, 3),
            )
            self._models[key] = loaded
            logger.info("Loaded %s (%s) in %.2fs", key, model_id, elapsed)
            return loaded

    def _place(self, model: Any) -> Any:
        device = self.resolve_device()
        try:
            model = model.to(device)
        except Exception as exc:  # pragma: no cover - device placement failure
            raise ModelLoadError(
                f"Could not move the model onto device {device!r}: {exc}",
                remediation=[
                    "Set SATQUERY_DEVICE=cpu to run without an accelerator.",
                    "On CUDA, confirm the GPU has free memory with `nvidia-smi`.",
                ],
            ) from exc
        model.eval()
        return model

    # -- Concrete models ---------------------------------------------------

    def clip(self) -> LoadedModel:
        """CLIP, used for scene classification, grounding, and presence checks."""

        def build() -> Tuple[Any, Any, str]:
            transformers = require_transformers()
            require_torch()
            model_id = self.settings.clip_model
            kwargs = self.settings.hf_kwargs()
            try:
                processor = transformers.CLIPProcessor.from_pretrained(model_id, **kwargs)
                model = transformers.CLIPModel.from_pretrained(
                    model_id, torch_dtype=self.resolve_dtype(), **kwargs
                )
            except Exception as exc:
                raise ModelLoadError(
                    f"Could not load the CLIP model {model_id!r}: {exc}",
                    remediation=[
                        "Check SATQUERY_CLIP_MODEL names a real HuggingFace repo or local path.",
                        "For gated or private repos set SATQUERY_HF_TOKEN.",
                        "For an air-gapped run, pre-download the weights and set "
                        "SATQUERY_HF_LOCAL_ONLY=true with SATQUERY_HF_CACHE.",
                    ],
                    context={"model_id": model_id},
                ) from exc
            return self._place(model), processor, model_id

        return self._load("clip", build)

    def captioner(self) -> LoadedModel:
        """BLIP conditional captioning."""

        def build() -> Tuple[Any, Any, str]:
            transformers = require_transformers()
            require_torch()
            model_id = self.settings.caption_model
            kwargs = self.settings.hf_kwargs()
            try:
                processor = transformers.BlipProcessor.from_pretrained(model_id, **kwargs)
                model = transformers.BlipForConditionalGeneration.from_pretrained(
                    model_id, torch_dtype=self.resolve_dtype(), **kwargs
                )
            except Exception as exc:
                raise ModelLoadError(
                    f"Could not load the captioning model {model_id!r}: {exc}",
                    remediation=[
                        "SATQUERY_CAPTION_MODEL must name a BLIP conditional-generation "
                        "checkpoint, for example Salesforce/blip-image-captioning-large.",
                        "For gated or private repos set SATQUERY_HF_TOKEN.",
                    ],
                    context={"model_id": model_id},
                ) from exc
            return self._place(model), processor, model_id

        return self._load("captioner", build)

    def vqa(self) -> LoadedModel:
        """BLIP visual question answering."""

        def build() -> Tuple[Any, Any, str]:
            transformers = require_transformers()
            require_torch()
            model_id = self.settings.vqa_model
            kwargs = self.settings.hf_kwargs()
            try:
                processor = transformers.BlipProcessor.from_pretrained(model_id, **kwargs)
                model = transformers.BlipForQuestionAnswering.from_pretrained(
                    model_id, torch_dtype=self.resolve_dtype(), **kwargs
                )
            except Exception as exc:
                raise ModelLoadError(
                    f"Could not load the VQA model {model_id!r}: {exc}",
                    remediation=[
                        "SATQUERY_VQA_MODEL must name a BLIP question-answering checkpoint, "
                        "for example Salesforce/blip-vqa-base.",
                        "For gated or private repos set SATQUERY_HF_TOKEN.",
                    ],
                    context={"model_id": model_id},
                ) from exc
            return self._place(model), processor, model_id

        return self._load("vqa", build)

    def rsvlm(self) -> LoadedModel:
        """The optional stronger remote-sensing VLM."""
        if not self.settings.strong_backend_requested:
            raise ResourceNotConfiguredError(
                "No remote-sensing VLM is configured.",
                remediation=[
                    "Set SATQUERY_RSVLM_PATH to a checkpoint directory or HuggingFace repo id, "
                    "and SATQUERY_RSVLM_ENABLED=true.",
                    "Leave it unset to use the practical BLIP + CLIP path instead.",
                ],
            )

        def build() -> Tuple[Any, Any, str]:
            transformers = require_transformers()
            torch = require_torch()
            model_id = str(self.settings.rsvlm_path)

            local_candidate = Path(model_id).expanduser()
            if local_candidate.exists() and not local_candidate.is_dir():
                raise ModelLoadError(
                    f"SATQUERY_RSVLM_PATH points at {model_id!r}, which is a file, not a "
                    "checkpoint directory.",
                    remediation=[
                        "Point it at the directory containing config.json and the weight shards.",
                    ],
                )
            if local_candidate.is_dir():
                model_id = str(local_candidate.resolve())
                if not (local_candidate / "config.json").is_file():
                    raise ModelLoadError(
                        f"{model_id} has no config.json, so it is not a loadable checkpoint.",
                        remediation=[
                            "Confirm the download completed and the directory is the model root.",
                        ],
                    )

            kwargs = dict(self.settings.hf_kwargs())
            if self.settings.rsvlm_trust_remote_code:
                kwargs["trust_remote_code"] = True

            try:
                processor = transformers.AutoProcessor.from_pretrained(model_id, **kwargs)
            except Exception as exc:
                raise ModelLoadError(
                    f"Could not load a processor for the RS VLM at {model_id!r}: {exc}",
                    remediation=[
                        "Confirm the checkpoint ships a processor / tokenizer config.",
                        "Some community checkpoints need SATQUERY_RSVLM_TRUST_REMOTE_CODE=true.",
                    ],
                    context={"model_id": model_id},
                ) from exc

            kind = self.settings.rsvlm_kind
            if kind == "auto":
                kind = self._probe_rsvlm_kind(model_id, transformers, kwargs)

            loader_map = {
                "vision2seq": "AutoModelForVision2Seq",
                "causal_lm": "AutoModelForCausalLM",
                "blip2": "Blip2ForConditionalGeneration",
            }
            loader_name = loader_map[kind]
            loader = getattr(transformers, loader_name, None)
            if loader is None:
                raise ModelLoadError(
                    f"This transformers build has no {loader_name}.",
                    remediation=["Upgrade transformers: pip install -U transformers"],
                )

            try:
                model = loader.from_pretrained(
                    model_id, torch_dtype=self.resolve_dtype(), **kwargs
                )
            except Exception as exc:
                raise ModelLoadError(
                    f"Could not load the RS VLM at {model_id!r} using {loader_name}: {exc}",
                    remediation=[
                        "Set SATQUERY_RSVLM_KIND explicitly to vision2seq, causal_lm, or blip2.",
                        "Check that the weights finished downloading and are not corrupt.",
                        "Large checkpoints may need `pip install accelerate` and more free VRAM.",
                    ],
                    context={"model_id": model_id, "loader": loader_name},
                ) from exc

            del torch  # imported for the availability check only
            return self._place(model), processor, model_id

        return self._load("rsvlm", build)

    @staticmethod
    def _probe_rsvlm_kind(model_id: str, transformers: Any, kwargs: Dict[str, Any]) -> str:
        """Inspect the checkpoint config to choose a loader class."""
        try:
            config = transformers.AutoConfig.from_pretrained(model_id, **kwargs)
        except Exception:
            return "vision2seq"

        architectures = [str(name).lower() for name in (getattr(config, "architectures", None) or [])]
        model_type = str(getattr(config, "model_type", "")).lower()
        blob = " ".join(architectures + [model_type])

        if "blip2" in blob:
            return "blip2"
        if any(token in blob for token in ("vision2seq", "llava", "qwen2vl", "qwen2_vl", "idefics", "paligemma", "instructblip")):
            return "vision2seq"
        if "causallm" in blob or "causal_lm" in blob:
            return "causal_lm"
        return "vision2seq"

    # -- Introspection -----------------------------------------------------

    def loaded_keys(self) -> List[str]:
        return sorted(self._models)

    def is_loaded(self, key: str) -> bool:
        return key in self._models

    def status(self) -> Dict[str, Any]:
        """Non-loading availability report, safe to call from /health."""
        deps = probe_dependencies()
        torch_ok = bool(deps.get("torch", {}).get("installed"))
        transformers_ok = bool(deps.get("transformers", {}).get("installed"))
        practical_ok = torch_ok and transformers_ok

        rsvlm_reason: Optional[str] = None
        if not self.settings.strong_backend_requested:
            rsvlm_reason = "not configured (SATQUERY_RSVLM_PATH is unset)"
        elif not practical_ok:
            rsvlm_reason = "torch and transformers must be installed"
        elif self.settings.rsvlm_path and not str(self.settings.rsvlm_path).strip():
            rsvlm_reason = "SATQUERY_RSVLM_PATH is blank"

        device = "cpu"
        try:
            device = self.resolve_device()
        except Exception:  # device probing must never break /health
            device = self.settings.device

        return {
            "device": device,
            "dtype": self.settings.dtype,
            "practical": {
                "available": practical_ok,
                "reason": None if practical_ok else "torch and transformers must be installed",
                "caption_model": self.settings.caption_model,
                "vqa_model": self.settings.vqa_model,
                "clip_model": self.settings.clip_model,
                "loaded": [key for key in self.loaded_keys() if key != "rsvlm"],
            },
            "rsvlm": {
                "available": rsvlm_reason is None,
                "reason": rsvlm_reason,
                "path": self.settings.rsvlm_path,
                "kind": self.settings.rsvlm_kind,
                "loaded": self.is_loaded("rsvlm"),
            },
            "planner_llm": {
                "available": self.settings.llm_available,
                "reason": None if self.settings.llm_available else "no API key set",
                "model": self.settings.llm_model,
                "base_url": self.settings.llm_base_url,
                "mode": self.settings.router_mode,
            },
        }

    def unload(self) -> None:
        """Drop every cached model and release accelerator memory."""
        with self._registry_lock:
            self._models.clear()
        if _has_module("torch"):
            torch = importlib.import_module("torch")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
