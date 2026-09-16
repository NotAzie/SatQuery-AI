"""Configuration for SatQuery AI.

Everything that could differ between a laptop, a lab GPU box, and a judging
venue is read from the environment: model identifiers, checkpoint paths,
device selection, API credentials, and the limits that keep a single request
from eating the machine.

Nothing here imports torch or transformers. The configuration layer has to be
loadable on a machine that has neither, so that `satquery.config` can tell the
operator what is missing instead of dying on an import.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .errors import ConfigurationError

_TRUE = {"1", "true", "yes", "on", "y", "t"}
_FALSE = {"0", "false", "no", "off", "n", "f"}


def load_dotenv(path: str | os.PathLike[str] = ".env", *, override: bool = False) -> Dict[str, str]:
    """Minimal .env reader.

    Uses python-dotenv when it is installed, and otherwise falls back to a
    small parser so that the project has one less hard dependency. Supports
    `KEY=value`, `export KEY=value`, `#` comments, and single or double
    quoted values.
    """
    target = Path(path)
    if not target.is_file():
        return {}

    try:  # pragma: no cover - exercised only when python-dotenv is installed
        from dotenv import dotenv_values  # type: ignore

        parsed = {k: v for k, v in dotenv_values(str(target)).items() if v is not None}
    except ImportError:
        parsed = {}
        for raw_line in target.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            if key:
                parsed[key] = value

    for key, value in parsed.items():
        if override or key not in os.environ:
            os.environ[key] = value
    return parsed


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ConfigurationError(
        f"{name} must be a boolean-like value, got {raw!r}.",
        remediation=[f"Set {name} to one of: true, false, 1, 0, yes, no."],
    )


def _env_int(name: str, default: int, *, minimum: Optional[int] = None) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"{name} must be an integer, got {raw!r}.",
            remediation=[f"Set {name} to a whole number."],
        ) from exc
    if minimum is not None and value < minimum:
        raise ConfigurationError(
            f"{name} must be at least {minimum}, got {value}.",
            remediation=[f"Raise {name} to {minimum} or above."],
        )
    return value


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"{name} must be a number, got {raw!r}.",
            remediation=[f"Set {name} to a decimal number."],
        ) from exc


def _env_float_list(name: str, default: Tuple[float, ...]) -> Tuple[float, ...]:
    raw = _env(name)
    if raw is None:
        return default
    parts = [piece.strip() for piece in raw.replace(";", ",").split(",") if piece.strip()]
    try:
        values = tuple(float(piece) for piece in parts)
    except ValueError as exc:
        raise ConfigurationError(
            f"{name} must be a comma-separated list of numbers, got {raw!r}.",
            remediation=[f"Example: {name}=0.5,0.33,0.25"],
        ) from exc
    if not values:
        return default
    return values


DEVICE_CHOICES = {"auto", "cpu", "cuda", "mps"}
DTYPE_CHOICES = {"auto", "float32", "float16", "bfloat16"}
ROUTER_CHOICES = {"rules", "llm", "hybrid"}
RSVLM_KIND_CHOICES = {"auto", "vision2seq", "causal_lm", "blip2", "geochat"}


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the runtime configuration."""

    # -- Identity -----------------------------------------------------------
    app_name: str = "SatQuery AI"
    app_version: str = "1.0.0"
    owner: str = "Az"
    problem_statement: str = "SIH26167"

    # -- Compute ------------------------------------------------------------
    device: str = "auto"
    dtype: str = "auto"
    inference_batch_size: int = 16

    # -- Practical vision backend (HuggingFace) -----------------------------
    caption_model: str = "Salesforce/blip-image-captioning-large"
    vqa_model: str = "Salesforce/blip-vqa-base"
    clip_model: str = "openai/clip-vit-large-patch14"
    hf_token: Optional[str] = None
    hf_cache_dir: Optional[str] = None
    hf_local_files_only: bool = False
    caption_max_new_tokens: int = 48
    vqa_max_new_tokens: int = 24

    # -- Strong remote-sensing VLM backend (optional) -----------------------
    rsvlm_enabled: bool = False
    rsvlm_path: Optional[str] = None
    rsvlm_kind: str = "auto"
    rsvlm_max_new_tokens: int = 320
    rsvlm_temperature: float = 0.2
    rsvlm_trust_remote_code: bool = False
    geochat_source_path: Optional[str] = None
    rsvlm_system_prompt: str = (
        "You are a remote sensing image analyst. Answer only from what is visible "
        "in the imagery. Be specific about land cover, structures, and spatial "
        "layout. If the image does not support an answer, say so plainly."
    )

    # -- Planning LLM (optional) --------------------------------------------
    router_mode: str = "hybrid"
    llm_api_key: Optional[str] = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_s: float = 20.0

    # -- Imagery handling ---------------------------------------------------
    max_image_pixels: int = 1536
    max_upload_mb: float = 40.0
    allow_image_paths: bool = True
    image_root: Optional[str] = None

    # -- Grounding ----------------------------------------------------------
    grounding_scales: Tuple[float, ...] = (0.5, 0.35, 0.25, 0.18)
    grounding_max_windows: int = 320
    grounding_stride_ratio: float = 0.5
    grounding_min_region_frac: float = 0.0035
    grounding_max_regions: int = 24
    grounding_percentile: float = 88.0

    # -- Change detection ---------------------------------------------------
    change_patch_grid: int = 16
    change_min_region_frac: float = 0.004

    # -- Caching / serving --------------------------------------------------
    cache_size: int = 128
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: Tuple[str, ...] = ()

    # -- Derived ------------------------------------------------------------
    extras: Dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    # ----------------------------------------------------------------------

    @classmethod
    def from_env(cls, *, dotenv_path: Optional[str] = ".env") -> "Settings":
        if dotenv_path:
            load_dotenv(dotenv_path)

        device = (_env("SATQUERY_DEVICE", "auto") or "auto").lower()
        if device not in DEVICE_CHOICES:
            raise ConfigurationError(
                f"SATQUERY_DEVICE must be one of {sorted(DEVICE_CHOICES)}, got {device!r}.",
                remediation=["Set SATQUERY_DEVICE=auto to let SatQuery pick the best device."],
            )

        dtype = (_env("SATQUERY_DTYPE", "auto") or "auto").lower()
        if dtype not in DTYPE_CHOICES:
            raise ConfigurationError(
                f"SATQUERY_DTYPE must be one of {sorted(DTYPE_CHOICES)}, got {dtype!r}.",
                remediation=["Set SATQUERY_DTYPE=auto unless you need to pin precision."],
            )

        router_mode = (_env("SATQUERY_ROUTER", "hybrid") or "hybrid").lower()
        if router_mode not in ROUTER_CHOICES:
            raise ConfigurationError(
                f"SATQUERY_ROUTER must be one of {sorted(ROUTER_CHOICES)}, got {router_mode!r}.",
                remediation=[
                    "rules  - deterministic keyword routing, no API key needed",
                    "llm    - always ask the planning LLM (requires an API key)",
                    "hybrid - rules first, LLM only for ambiguous queries (default)",
                ],
            )

        rsvlm_kind = (_env("SATQUERY_RSVLM_KIND", "auto") or "auto").lower()
        if rsvlm_kind not in RSVLM_KIND_CHOICES:
            raise ConfigurationError(
                f"SATQUERY_RSVLM_KIND must be one of {sorted(RSVLM_KIND_CHOICES)}.",
                remediation=[
                    "auto        - probe the checkpoint config and pick a loader",
                    "vision2seq  - LLaVA / Qwen-VL style AutoModelForVision2Seq",
                    "causal_lm   - multimodal causal LM checkpoints",
                    "blip2       - BLIP-2 style conditional generation",
                ],
            )

        rsvlm_path = _env("SATQUERY_RSVLM_PATH")
        geochat_source_path = _env("SATQUERY_GEOCHAT_SOURCE_PATH")
        rsvlm_enabled = _env_bool("SATQUERY_RSVLM_ENABLED", bool(rsvlm_path))
        if rsvlm_enabled and not rsvlm_path:
            raise ConfigurationError(
                "SATQUERY_RSVLM_ENABLED is true but SATQUERY_RSVLM_PATH is empty.",
                remediation=[
                    "Point SATQUERY_RSVLM_PATH at a local checkpoint directory or a "
                    "HuggingFace repo id.",
                    "Or set SATQUERY_RSVLM_ENABLED=false to use the practical BLIP/CLIP path.",
                ],
            )

        image_root = _env("SATQUERY_IMAGE_ROOT")
        if image_root:
            resolved_root = Path(image_root).expanduser()
            if not resolved_root.is_dir():
                raise ConfigurationError(
                    f"SATQUERY_IMAGE_ROOT points at {image_root!r}, which is not a directory.",
                    remediation=["Create the directory or clear SATQUERY_IMAGE_ROOT."],
                )
            image_root = str(resolved_root.resolve())

        cors_raw = _env("SATQUERY_CORS_ORIGINS", "")
        cors_origins = tuple(
            piece.strip() for piece in (cors_raw or "").split(",") if piece.strip()
        )

        settings = cls(
            device=device,
            dtype=dtype,
            inference_batch_size=_env_int("SATQUERY_BATCH_SIZE", 16, minimum=1),
            caption_model=_env("SATQUERY_CAPTION_MODEL", cls.caption_model) or cls.caption_model,
            vqa_model=_env("SATQUERY_VQA_MODEL", cls.vqa_model) or cls.vqa_model,
            clip_model=_env("SATQUERY_CLIP_MODEL", cls.clip_model) or cls.clip_model,
            hf_token=_env("SATQUERY_HF_TOKEN") or _env("HF_TOKEN") or _env("HUGGINGFACE_TOKEN"),
            hf_cache_dir=_env("SATQUERY_HF_CACHE") or _env("HF_HOME"),
            hf_local_files_only=_env_bool("SATQUERY_HF_LOCAL_ONLY", False),
            caption_max_new_tokens=_env_int("SATQUERY_CAPTION_MAX_TOKENS", 48, minimum=8),
            vqa_max_new_tokens=_env_int("SATQUERY_VQA_MAX_TOKENS", 24, minimum=2),
            rsvlm_enabled=rsvlm_enabled,
            rsvlm_path=rsvlm_path,
            rsvlm_kind=rsvlm_kind,
            rsvlm_max_new_tokens=_env_int("SATQUERY_RSVLM_MAX_TOKENS", 320, minimum=16),
            rsvlm_temperature=_env_float("SATQUERY_RSVLM_TEMPERATURE", 0.2),
            rsvlm_trust_remote_code=_env_bool("SATQUERY_RSVLM_TRUST_REMOTE_CODE", False),
            geochat_source_path=geochat_source_path,
            rsvlm_system_prompt=_env("SATQUERY_RSVLM_SYSTEM_PROMPT", cls.rsvlm_system_prompt)
            or cls.rsvlm_system_prompt,
            router_mode=router_mode,
            llm_api_key=_env("SATQUERY_LLM_API_KEY") or _env("OPENAI_API_KEY"),
            llm_base_url=(_env("SATQUERY_LLM_BASE_URL", cls.llm_base_url) or cls.llm_base_url).rstrip("/"),
            llm_model=_env("SATQUERY_LLM_MODEL", cls.llm_model) or cls.llm_model,
            llm_timeout_s=_env_float("SATQUERY_LLM_TIMEOUT", 20.0),
            max_image_pixels=_env_int("SATQUERY_MAX_IMAGE_PX", 1536, minimum=224),
            max_upload_mb=_env_float("SATQUERY_MAX_UPLOAD_MB", 40.0),
            allow_image_paths=_env_bool("SATQUERY_ALLOW_IMAGE_PATHS", True),
            image_root=image_root,
            grounding_scales=_env_float_list("SATQUERY_GROUNDING_SCALES", cls.grounding_scales),
            grounding_max_windows=_env_int("SATQUERY_GROUNDING_MAX_WINDOWS", 320, minimum=16),
            grounding_stride_ratio=_env_float("SATQUERY_GROUNDING_STRIDE_RATIO", 0.5),
            grounding_min_region_frac=_env_float("SATQUERY_GROUNDING_MIN_REGION_FRAC", 0.0035),
            grounding_max_regions=_env_int("SATQUERY_GROUNDING_MAX_REGIONS", 24, minimum=1),
            grounding_percentile=_env_float("SATQUERY_GROUNDING_PERCENTILE", 88.0),
            change_patch_grid=_env_int("SATQUERY_CHANGE_PATCH_GRID", 16, minimum=4),
            change_min_region_frac=_env_float("SATQUERY_CHANGE_MIN_REGION_FRAC", 0.004),
            cache_size=_env_int("SATQUERY_CACHE_SIZE", 128, minimum=0),
            host=_env("SATQUERY_HOST", cls.host) or cls.host,
            port=_env_int("SATQUERY_PORT", 8000, minimum=1),
            cors_origins=cors_origins,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not 0.0 < self.grounding_stride_ratio <= 1.0:
            raise ConfigurationError(
                "SATQUERY_GROUNDING_STRIDE_RATIO must fall in (0, 1].",
                remediation=["0.5 means windows overlap by half; 1.0 means no overlap."],
            )
        if not 0.0 < self.grounding_percentile < 100.0:
            raise ConfigurationError(
                "SATQUERY_GROUNDING_PERCENTILE must fall in (0, 100).",
                remediation=["88 keeps roughly the top eighth of the response map."],
            )
        for scale in self.grounding_scales:
            if not 0.02 < scale <= 1.0:
                raise ConfigurationError(
                    f"Grounding scale {scale} is outside the usable range (0.02, 1.0].",
                    remediation=["Scales are window sizes as a fraction of the shorter edge."],
                )
        if self.router_mode == "llm" and not self.llm_api_key:
            raise ConfigurationError(
                "SATQUERY_ROUTER=llm requires a planning LLM API key.",
                remediation=[
                    "Set OPENAI_API_KEY (or SATQUERY_LLM_API_KEY).",
                    "Or set SATQUERY_ROUTER=rules to use deterministic routing only.",
                ],
            )

    # ----------------------------------------------------------------------

    @property
    def llm_available(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def strong_backend_requested(self) -> bool:
        return self.rsvlm_enabled and bool(self.rsvlm_path)

    def hf_kwargs(self) -> Dict[str, Any]:
        """Keyword arguments shared by every `from_pretrained` call."""
        kwargs: Dict[str, Any] = {}
        if self.hf_token:
            kwargs["token"] = self.hf_token
        if self.hf_cache_dir:
            kwargs["cache_dir"] = self.hf_cache_dir
        if self.hf_local_files_only:
            kwargs["local_files_only"] = True
        return kwargs

    def describe(self) -> Dict[str, Any]:
        """Redacted view of the configuration, safe to return over the API."""
        payload: Dict[str, Any] = {}
        for item in fields(self):
            if item.name == "extras":
                continue
            value = getattr(self, item.name)
            if isinstance(value, tuple):
                value = list(value)
            payload[item.name] = value
        payload["hf_token"] = "set" if self.hf_token else None
        payload["llm_api_key"] = "set" if self.llm_api_key else None
        return payload


_SETTINGS: Optional[Settings] = None


def get_settings(*, refresh: bool = False, dotenv_path: Optional[str] = ".env") -> Settings:
    """Process-wide settings singleton."""
    global _SETTINGS
    if _SETTINGS is None or refresh:
        _SETTINGS = Settings.from_env(dotenv_path=dotenv_path)
    return _SETTINGS


def set_settings(settings: Settings) -> None:
    """Override the singleton. Used by tests and embedding applications."""
    global _SETTINGS
    _SETTINGS = settings
