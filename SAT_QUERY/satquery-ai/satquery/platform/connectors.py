"""Connector lifecycle, acquisition policy, and asynchronous rate limiting."""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import importlib.util
import json
import logging
import math
import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Optional, Protocol

from ..errors import (
    AuthenticationError,
    CacheError,
    ConnectorError,
    ExtensionError,
    OperationTimeoutError,
    ValidationError,
)
from .cache import CacheBackend
from .contracts import (
    ConnectorDiagnostic,
    ConnectorManifest,
    ConnectorMetadata,
    DatasetMetadata,
    DatasetReference,
    EarthQuery,
    Observation,
    ObservationSearchResult,
)
from .datasets import DatasetRegistry, InMemoryDatasetRegistry
from .modalities import infer_modalities
from .observability import log_event, redact_sensitive
from .registry import ComponentRegistry

_IN_POLICY_OBSERVATION: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "satquery_in_policy_observation", default=False
)
_POLICY_USED: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "satquery_observation_policy_used", default=False
)


@dataclass(frozen=True)
class ConnectorPolicy:
    timeout_seconds: Optional[float] = None
    max_attempts: int = 1
    retry_safe: bool = False
    retry_delay_seconds: float = 0.25
    requests_per_second: Optional[float] = None
    cache_ttl_seconds: Optional[float] = None

    def __post_init__(self) -> None:
        if self.timeout_seconds is not None and (
            not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be greater than zero or None")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if self.max_attempts > 1 and not self.retry_safe:
            raise ValueError("multiple attempts require retry_safe=True")
        if not math.isfinite(self.retry_delay_seconds) or self.retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must not be negative")
        if self.requests_per_second is not None and (
            not math.isfinite(self.requests_per_second)
            or self.requests_per_second <= 0
        ):
            raise ValueError("requests_per_second must be greater than zero or None")
        if self.cache_ttl_seconds is not None and (
            not math.isfinite(self.cache_ttl_seconds)
            or self.cache_ttl_seconds <= 0
        ):
            raise ValueError("cache_ttl_seconds must be greater than zero or None")


class AuthenticationProvider(Protocol):
    """Resolve connector credentials without coupling connectors to secret stores."""

    async def credentials_for(
        self, connector_id: str, schemes: tuple[str, ...]
    ) -> Optional[Mapping[str, str]]: ...


class AsyncRateLimiter:
    """Spaces connector starts at a configured average request rate."""

    def __init__(self, requests_per_second: Optional[float]) -> None:
        if requests_per_second is not None and requests_per_second <= 0:
            raise ValueError("requests_per_second must be greater than zero or None")
        self._interval = 1.0 / requests_per_second if requests_per_second else None
        self._next_allowed = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self._interval is None:
            return
        async with self._lock:
            now = time.monotonic()
            delay = max(self._next_allowed - now, 0.0)
            if delay:
                await asyncio.sleep(delay)
            self._next_allowed = max(now, self._next_allowed) + self._interval


class Connector(ABC):
    """Base contract for local, remote, synchronous, and streaming sources."""

    def __init__(
        self,
        *,
        configuration: Optional[Mapping[str, Any]] = None,
        policy: Optional[ConnectorPolicy] = None,
        cache: Optional[CacheBackend] = None,
        platform_config: Any = None,
    ) -> None:
        self.configuration = dict(configuration or {})
        self.policy = (
            policy
            or (platform_config.connector_policy() if platform_config is not None else None)
            or ConnectorPolicy()
        )
        configured_cache = (
            platform_config.create_cache()
            if platform_config is not None and cache is None
            else None
        )
        self.cache = cache if cache is not None else configured_cache
        self._rate_limiter = AsyncRateLimiter(self.policy.requests_per_second)
        self._lifecycle_lock = asyncio.Lock()
        self._started = False
        self._state: Literal[
            "stopped", "starting", "running", "degraded", "failed"
        ] = "stopped"
        self._calls = 0
        self._failures = 0
        self._consecutive_failures = 0
        self._retries = 0
        self._last_success_at: Optional[datetime] = None
        self._last_failure_at: Optional[datetime] = None
        self._last_error_type: Optional[str] = None
        self._last_error: Optional[str] = None
        self._last_duration_seconds: Optional[float] = None
        self._duration_total = 0.0
        self._health_samples: deque[bool] = deque(maxlen=100)
        self._health_probe_count = 0
        self._last_health_probe_at: Optional[datetime] = None
        self._last_health_probe_duration_seconds: Optional[float] = None

    @property
    @abstractmethod
    def metadata(self) -> ConnectorMetadata:
        """Stable identity, capabilities, authentication, and data discovery."""

    async def open(self) -> None:
        """Acquire connector-local resources before authentication or requests."""

    async def close(self) -> None:
        """Release connector-local resources; safe to call more than once."""

    @property
    def manifest(self) -> ConnectorManifest:
        metadata = self.metadata
        return ConnectorManifest(
            metadata=metadata,
            dependencies=metadata.dependencies,
            authentication_schemes=metadata.authentication_schemes,
            configuration_schema=metadata.configuration_schema,
            quota=metadata.quota,
            lifecycle_hooks=tuple(
                name
                for name in ("open", "authenticate", "discover", "close")
                if getattr(type(self), name) is not getattr(Connector, name, None)
            ),
        )

    def validate(self) -> tuple[str, ...]:
        """Validate dependency availability and manifest identity."""
        errors: list[str] = []
        if self.manifest.metadata.connector_id != self.metadata.connector_id:
            errors.append("manifest connector id differs from runtime metadata")
        for dependency in self.manifest.dependencies:
            if importlib.util.find_spec(dependency) is None:
                errors.append(f"required dependency {dependency!r} is unavailable")
        return tuple(errors)

    @property
    def diagnostics(self) -> ConnectorDiagnostic:
        calls = self._calls
        average = self._duration_total / calls if calls else None
        availability = (
            sum(self._health_samples) / len(self._health_samples)
            if self._health_samples
            else None
        )
        health = (
            "unhealthy"
            if self._state == "failed"
            else "degraded"
            if self._consecutive_failures
            else "healthy"
            if calls
            else self.metadata.health
        )
        return ConnectorDiagnostic(
            connector_id=self.metadata.connector_id,
            state=self._state,
            health=health,
            calls=calls,
            failures=self._failures,
            retries=self._retries,
            last_success_at=self._last_success_at,
            last_failure_at=self._last_failure_at,
            last_error_type=self._last_error_type,
            last_error=self._last_error,
            last_duration_seconds=self._last_duration_seconds,
            average_duration_seconds=average,
            availability_ratio=availability,
            health_probe_count=self._health_probe_count,
            last_health_probe_at=self._last_health_probe_at,
            last_health_probe_duration_seconds=(
                self._last_health_probe_duration_seconds
            ),
        )

    async def probe(self) -> None:
        """Perform a lightweight provider-specific connectivity check."""
        raise NotImplementedError

    async def health_check(self, *, active: bool = False) -> ConnectorDiagnostic:
        """Return local health, optionally recording an active provider probe."""
        errors = self.validate()
        if errors:
            return self.diagnostics.model_copy(
                update={
                    "state": "failed",
                    "health": "unhealthy",
                    "metadata": {"validation_errors": errors},
                }
            )
        if not active:
            return self.diagnostics
        if type(self).probe is Connector.probe:
            return self.diagnostics.model_copy(
                update={
                    "metadata": {"active_probe": "unsupported"},
                }
            )
        started = time.perf_counter()
        self._last_health_probe_at = datetime.now(timezone.utc)
        self._health_probe_count += 1
        try:
            await self.probe()
        except Exception as exc:
            duration = time.perf_counter() - started
            self._health_samples.append(False)
            self._last_health_probe_duration_seconds = max(duration, 0.0)
            self._state = "degraded" if self._started else "failed"
            return self.diagnostics.model_copy(
                update={
                    "health": "unhealthy",
                    "metadata": {
                        "active_probe": "failed",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                }
            )
        duration = time.perf_counter() - started
        self._health_samples.append(True)
        self._last_health_probe_duration_seconds = max(duration, 0.0)
        if self._started:
            self._state = "running"
        return self.diagnostics.model_copy(
            update={
                "health": "healthy",
                "metadata": {"active_probe": "successful"},
            }
        )

    async def authenticate(self, credentials: Optional[Mapping[str, str]]) -> None:
        metadata = self.metadata
        authentication_required = (
            bool(metadata.authentication_schemes)
            if metadata.authentication_required is None
            else metadata.authentication_required
        )
        if authentication_required and not credentials:
            raise AuthenticationError(
                f"Connector {metadata.connector_id!r} requires authentication.",
                context={
                    "connector": metadata.connector_id,
                    "schemes": list(metadata.authentication_schemes),
                },
            )
        if credentials:
            await self._authenticate(credentials or {})

    async def _authenticate(self, credentials: Mapping[str, str]) -> None:
        """Override this hook when a connector declares authentication."""
        raise AuthenticationError(
            f"Connector {self.metadata.connector_id!r} does not implement "
            "its declared authentication scheme.",
            context={
                "connector": self.metadata.connector_id,
                "credential_fields": sorted(credentials),
            },
        )

    async def start(self, credentials: Optional[Mapping[str, str]] = None) -> None:
        async with self._lifecycle_lock:
            if self._started:
                return
            self._state = "starting"
            try:
                await self.open()
                await self.authenticate(credentials)
            except Exception as exc:
                try:
                    await self.close()
                except Exception:
                    self._state = "failed"
                    raise
                self._state = "failed"
                self._record_failure(exc)
                raise
            self._started = True
            self._state = "running"

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            if not self._started:
                return
            try:
                await self.close()
            finally:
                self._started = False
                self._state = "stopped"

    @abstractmethod
    async def discover(self) -> tuple[DatasetReference, ...]:
        """Return datasets this connector can currently expose."""

    @abstractmethod
    async def acquire(self, request: Mapping[str, Any]) -> Any:
        """Acquire one connector response; implementations may use thread offload."""

    async def stream(self, request: Mapping[str, Any]) -> AsyncIterator[Any]:
        """Default stream yields the single response from :meth:`acquire`."""
        response = await self.acquire(request)
        if isinstance(response, AsyncIterator):
            async for item in response:
                yield item
        else:
            yield response

    async def fetch(
        self,
        request: Mapping[str, Any],
        *,
        cache_key: Optional[str] = None,
        execution_context: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        """Acquire with timeout, bounded retries, rate limiting, and cache hooks."""
        inside_policy_observation = _IN_POLICY_OBSERVATION.get()
        request_already_started = _POLICY_USED.get()
        if inside_policy_observation:
            _POLICY_USED.set(True)
        key = cache_key or self._cache_key(request)
        if self.cache is not None and key is not None:
            try:
                found, cached = await self.cache.get(key)
            except Exception as exc:
                raise CacheError(
                    f"Cache lookup failed for connector {self.metadata.connector_id!r}: {exc}",
                    context={"connector": self.metadata.connector_id, "cache_key": key},
                ) from exc
            if found:
                log_event(
                    "connector.cache_hit",
                    connector=self.metadata.connector_id,
                    parameters=redact_sensitive(request),
                    **_execution_fields(execution_context),
                )
                return cached

        for attempt in range(1, self.policy.max_attempts + 1):
            if (
                not inside_policy_observation
                or request_already_started
                or attempt > 1
            ):
                await self._rate_limiter.acquire()
            started = time.perf_counter()
            process_cpu_started = time.process_time()
            try:
                operation = self.acquire(request)
                if self.policy.timeout_seconds is None:
                    result = await operation
                else:
                    try:
                        result = await asyncio.wait_for(
                            operation, timeout=self.policy.timeout_seconds
                        )
                    except asyncio.TimeoutError as exc:
                        raise OperationTimeoutError(
                            f"Connector {self.metadata.connector_id!r} exceeded "
                            f"{self.policy.timeout_seconds:g} seconds.",
                            context={
                                "connector": self.metadata.connector_id,
                                "timeout_seconds": self.policy.timeout_seconds,
                            },
                        ) from exc
            except ConnectorError as exc:
                self._record_failure(exc, duration=time.perf_counter() - started)
                should_retry = (
                    exc.recoverable
                    and self.policy.retry_safe
                    and attempt < self.policy.max_attempts
                )
                log_event(
                    "connector.retry" if should_retry else "connector.failed",
                    level=logging.WARNING if should_retry else logging.ERROR,
                    connector=self.metadata.connector_id,
                    attempt=attempt,
                    error_code=exc.code,
                    error=str(exc),
                    parameters=redact_sensitive(request),
                    **_execution_fields(execution_context),
                )
                if not should_retry:
                    raise
                self._retries += 1
                await asyncio.sleep(self.policy.retry_delay_seconds)
            except Exception as exc:
                self._record_failure(exc, duration=time.perf_counter() - started)
                error = ConnectorError(
                    f"Connector {self.metadata.connector_id!r} acquisition failed: {exc}",
                    context={
                        "connector": self.metadata.connector_id,
                        "attempt": attempt,
                    },
                )
                log_event(
                    "connector.failed",
                    level=logging.ERROR,
                    connector=self.metadata.connector_id,
                    attempt=attempt,
                    error=str(error),
                    error_type=type(exc).__name__,
                    parameters=redact_sensitive(request),
                    **_execution_fields(execution_context),
                )
                raise error from exc
            else:
                self._record_success(result, time.perf_counter() - started)
                if self.cache is not None and key is not None:
                    try:
                        await self.cache.set(
                            key, result, ttl_seconds=self.policy.cache_ttl_seconds
                        )
                    except Exception as exc:
                        raise CacheError(
                            f"Cache write failed for connector "
                            f"{self.metadata.connector_id!r}: {exc}",
                            context={
                                "connector": self.metadata.connector_id,
                                "cache_key": key,
                            },
                        ) from exc
                log_event(
                    "connector.acquisition",
                    connector=self.metadata.connector_id,
                    duration_seconds=time.perf_counter() - started,
                    attempt=attempt,
                    parameters=redact_sensitive(request),
                    dataset_version=getattr(
                        getattr(result, "dataset", None), "version", None
                    ),
                    resource_usage={
                        "process_cpu_seconds_delta": time.process_time()
                        - process_cpu_started
                    },
                    **_execution_fields(execution_context),
                )
                return result
        raise AssertionError("Connector retry loop exited without a result or error")

    def _record_success(self, _result: Any, duration: float) -> None:
        self._calls += 1
        self._duration_total += duration
        self._last_duration_seconds = max(duration, 0.0)
        self._last_success_at = datetime.now(timezone.utc)
        self._last_error = None
        self._last_error_type = None
        self._consecutive_failures = 0
        if self._started:
            self._state = "running"

    def _record_failure(
        self, error: Exception, *, duration: Optional[float] = None
    ) -> None:
        self._calls += 1
        self._failures += 1
        self._consecutive_failures += 1
        if duration is not None:
            self._duration_total += duration
            self._last_duration_seconds = max(duration, 0.0)
        self._last_failure_at = datetime.now(timezone.utc)
        self._last_error_type = type(error).__name__
        self._last_error = str(error)
        self._state = "degraded" if self._started else "failed"

    async def fetch_stream(self, request: Mapping[str, Any]) -> AsyncIterator[Any]:
        """Stream results with timeout and rate limiting.

        A failed stream is retried only before its first item, preventing
        duplicate output after partial delivery.
        """
        for attempt in range(1, self.policy.max_attempts + 1):
            await self._rate_limiter.acquire()
            emitted = False
            iterator = self.stream(request).__aiter__()
            try:
                while True:
                    try:
                        pending = iterator.__anext__()
                        item = (
                            await pending
                            if self.policy.timeout_seconds is None
                            else await asyncio.wait_for(
                                pending, timeout=self.policy.timeout_seconds
                            )
                        )
                    except StopAsyncIteration:
                        return
                    except asyncio.TimeoutError as exc:
                        raise OperationTimeoutError(
                            f"Connector {self.metadata.connector_id!r} stream "
                            "exceeded its configured timeout.",
                            context={"connector": self.metadata.connector_id},
                        ) from exc
                    emitted = True
                    yield item
            except ConnectorError as exc:
                self._record_failure(exc)
                if emitted or not exc.recoverable or attempt == self.policy.max_attempts:
                    raise
                self._retries += 1
                await asyncio.sleep(self.policy.retry_delay_seconds)
            except Exception as exc:
                self._record_failure(exc)
                raise ConnectorError(
                    f"Connector {self.metadata.connector_id!r} stream failed: {exc}",
                    context={"connector": self.metadata.connector_id, "attempt": attempt},
                ) from exc

    def _cache_key(self, request: Mapping[str, Any]) -> Optional[str]:
        if self.cache is None:
            return None
        try:
            encoded = json.dumps(
                request, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "Connector requests must be JSON-compatible when connector caching is enabled.",
                context={"connector": self.metadata.connector_id},
            ) from exc
        digest = hashlib.sha256(encoded).hexdigest()
        return f"{self.metadata.connector_id}:{digest}"


class PerceptionConnector(Connector, ABC):
    """Connector that accepts canonical Earth queries and returns observations."""

    @abstractmethod
    async def observe(self, query: EarthQuery) -> ObservationSearchResult:
        """Translate a canonical query and normalize source data at this boundary."""

    async def stream_observations(
        self, query: EarthQuery
    ) -> AsyncIterator[Observation]:
        result = await self.observe(query)
        for observation in result.observations:
            yield observation

    async def observe_with_policy(self, query: EarthQuery) -> ObservationSearchResult:
        """Execute canonical acquisition with timeout, rate and retry policy."""
        for attempt in range(1, self.policy.max_attempts + 1):
            await self._rate_limiter.acquire()
            used_token = _POLICY_USED.set(False)
            active_token = _IN_POLICY_OBSERVATION.set(True)
            started = time.perf_counter()
            try:
                operation = self.observe(query)
                if self.policy.timeout_seconds is None:
                    result = await operation
                else:
                    result = await asyncio.wait_for(
                        operation,
                        timeout=self.policy.timeout_seconds,
                    )
            except asyncio.TimeoutError as exc:
                error = OperationTimeoutError(
                    f"Connector {self.metadata.connector_id!r} exceeded "
                    f"{self.policy.timeout_seconds:g} seconds.",
                    context={
                        "connector": self.metadata.connector_id,
                        "timeout_seconds": self.policy.timeout_seconds,
                    },
                )
                if not _POLICY_USED.get():
                    self._record_failure(error, duration=time.perf_counter() - started)
                should_retry = (
                    not _POLICY_USED.get()
                    and self.policy.retry_safe
                    and attempt < self.policy.max_attempts
                )
                if not should_retry:
                    raise error from exc
                self._retries += 1
                await asyncio.sleep(self.policy.retry_delay_seconds)
            except ConnectorError as exc:
                used_policy = _POLICY_USED.get()
                if not used_policy:
                    self._record_failure(exc, duration=time.perf_counter() - started)
                should_retry = (
                    not used_policy
                    and exc.recoverable
                    and self.policy.retry_safe
                    and attempt < self.policy.max_attempts
                )
                if not should_retry:
                    raise
                self._retries += 1
                await asyncio.sleep(self.policy.retry_delay_seconds)
            except Exception as exc:
                error = ConnectorError(
                    f"Connector {self.metadata.connector_id!r} observation failed: {exc}",
                    context={"connector": self.metadata.connector_id, "attempt": attempt},
                )
                if not _POLICY_USED.get():
                    self._record_failure(error, duration=time.perf_counter() - started)
                raise error from exc
            else:
                if not _POLICY_USED.get():
                    self._record_success(result, time.perf_counter() - started)
                if not isinstance(result, ObservationSearchResult):
                    raise ConnectorError(
                        "Perception connector returned a non-canonical acquisition result.",
                        context={"connector": self.metadata.connector_id},
                    )
                return result
            finally:
                _IN_POLICY_OBSERVATION.reset(active_token)
                _POLICY_USED.reset(used_token)
        raise AssertionError("Observation retry loop exited without a result or error")


class ConnectorManager:
    """Owns connector instances and coordinates startup, discovery, and shutdown."""

    def __init__(
        self,
        registry: Optional[ComponentRegistry[Connector]] = None,
        *,
        dataset_registry: Optional[DatasetRegistry] = None,
        authentication_provider: Optional[AuthenticationProvider] = None,
    ) -> None:
        self.registry = registry if registry is not None else ComponentRegistry()
        self._started: set[str] = set()
        self._lock = asyncio.Lock()
        self.dataset_registry = (
            dataset_registry if dataset_registry is not None else InMemoryDatasetRegistry()
        )
        self.authentication_provider = authentication_provider

    def register(self, connector: Connector) -> None:
        validation_errors = connector.validate()
        if validation_errors:
            raise ConnectorError(
                f"Connector {connector.metadata.connector_id!r} failed validation.",
                context={
                    "connector": connector.metadata.connector_id,
                    "errors": validation_errors,
                },
            )
        self.registry.register(connector.metadata.connector_id, connector)
        if self.dataset_registry is not None and connector.metadata.datasets:
            try:
                self._register_dataset_references(
                    connector,
                    connector.metadata.datasets,
                    discovered=False,
                )
            except Exception:
                self.registry.unregister(connector.metadata.connector_id)
                raise

    def describe(self, connector_id: str) -> ConnectorManifest:
        return self.registry.get(connector_id).manifest

    def manifests(self) -> tuple[ConnectorManifest, ...]:
        return tuple(
            self.registry.get(connector_id).manifest
            for connector_id in self.registry.names()
        )

    def capabilities(self) -> dict[str, tuple[str, ...]]:
        return {
            connector_id: tuple(
                sorted(set(self.registry.get(connector_id).metadata.capabilities))
            )
            for connector_id in self.registry.names()
        }

    def discover_capabilities(self) -> dict[str, tuple[str, ...]]:
        """Return a deterministic reverse index of declared capabilities."""
        result: dict[str, list[str]] = {}
        for connector_id in self.registry.names():
            metadata = self.registry.get(connector_id).metadata
            for capability in metadata.capabilities:
                result.setdefault(capability, []).append(connector_id)
        return {
            capability: tuple(sorted(connector_ids))
            for capability, connector_ids in sorted(result.items())
        }

    def diagnostics(self) -> tuple[ConnectorDiagnostic, ...]:
        return tuple(
            self.registry.get(connector_id).diagnostics
            for connector_id in self.registry.names()
        )

    async def health_snapshot(
        self, *, active: bool = False
    ) -> tuple[ConnectorDiagnostic, ...]:
        """Collect local diagnostics or explicitly requested active probes."""
        return tuple(
            await asyncio.gather(
                *(
                    self.registry.get(connector_id).health_check(active=active)
                    for connector_id in self.registry.names()
                )
            )
        )

    def validate(self, connector_id: str) -> tuple[str, ...]:
        return self.registry.get(connector_id).validate()

    def discover_plugins(
        self, build: Callable[[Any], Connector]
    ) -> tuple[str, ...]:
        """Load trusted installed connector entry points through a caller builder."""

        def build_and_validate(entry_point: Any) -> tuple[str, Connector]:
            connector = build(entry_point)
            validation_errors = connector.validate()
            if validation_errors:
                raise ConnectorError(
                    f"Connector {connector.metadata.connector_id!r} failed validation.",
                    context={
                        "connector": connector.metadata.connector_id,
                        "errors": validation_errors,
                    },
                )
            return connector.metadata.connector_id, connector

        return self.registry.discover_entry_points(
            "satquery.connectors", build_and_validate
        )

    async def start(
        self,
        connector_id: str,
        credentials: Optional[Mapping[str, str]] = None,
    ) -> ConnectorMetadata:
        connector = self.registry.get(connector_id)
        if credentials is None and self.authentication_provider is not None:
            credentials = await self.authentication_provider.credentials_for(
                connector_id, connector.metadata.authentication_schemes
            )
        async with self._lock:
            await connector.start(credentials)
            self._started.add(connector_id)
        return connector.metadata

    async def discover(self, connector_id: str) -> tuple[DatasetReference, ...]:
        connector = self.registry.get(connector_id)
        await self._ensure_started(connector_id)
        try:
            references = await connector.discover()
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(
                f"Connector {connector_id!r} dataset discovery failed: {exc}",
                context={"connector": connector_id},
            ) from exc
        if self.dataset_registry is not None:
            self._register_dataset_references(connector, references, discovered=True)
        return references

    def _register_dataset_references(
        self,
        connector: Connector,
        references: tuple[DatasetReference, ...],
        *,
        discovered: bool,
    ) -> None:
        registry = self.dataset_registry
        if registry is None:
            return
        metadata = connector.metadata
        provider_name = metadata.provider_metadata.get("provider")
        provider = (
            provider_name
            if isinstance(provider_name, str) and provider_name.strip()
            else "unknown"
        )
        datasets: list[DatasetMetadata] = []
        for reference in references:
            raw = reference.metadata
            variables = raw.get("variables", metadata.supported_variables)
            declared_modalities = raw.get("modalities")
            if not isinstance(declared_modalities, (list, tuple)):
                declared_modalities = (
                    infer_modalities(variables)
                    or metadata.modalities
                )
            source = "automatic" if discovered else "connector-declaration"
            candidate: dict[str, Any] = {
                "connector_id": reference.connector_id,
                "dataset_id": reference.dataset_id,
                "provider": provider,
                "version": reference.version,
                "modalities": tuple(declared_modalities),
                "metadata": {
                    **raw,
                    "uri": reference.uri,
                    "discovery": "connector" if discovered else "declared",
                    "registration_source": source,
                },
            }
            for field in (
                "variables",
                "units",
                "modalities",
                "capabilities",
                "spatial_coverage",
                "temporal_coverage",
                "historical_coverage",
                "forecast_coverage",
                "supports_historical",
                "supports_forecast",
                "spatial_resolution",
                "resolution_unit",
                "crs",
                "update_frequency",
                "uncertainty_characteristics",
                "licensing",
                "citation",
                "latency",
                "access_policy",
                "quality_characteristics",
                "confidence_available",
                "tags",
                "keywords",
                "categories",
                "aliases",
                "deprecated",
                "assets",
            ):
                if field in raw:
                    candidate[field] = raw[field]
            datasets.append(DatasetMetadata.model_validate(candidate))

        for dataset in datasets:
            try:
                registry.register(dataset)
            except ExtensionError:
                current = registry.get(
                    dataset.connector_id,
                    dataset.dataset_id,
                    dataset.version,
                )
                source = current.metadata.get("registration_source")
                if discovered and source in {
                    "automatic",
                    "connector-declaration",
                }:
                    registry.register(dataset, replace=True)

    async def acquire(
        self,
        connector_id: str,
        request: Mapping[str, Any],
        *,
        cache_key: Optional[str] = None,
        execution_context: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        connector = self.registry.get(connector_id)
        await self._ensure_started(connector_id)
        return await connector.fetch(
            request,
            cache_key=cache_key,
            execution_context=execution_context,
        )

    async def stream(
        self, connector_id: str, request: Mapping[str, Any]
    ) -> AsyncIterator[Any]:
        connector = self.registry.get(connector_id)
        if not connector.metadata.supports_streaming:
            raise ConnectorError(
                f"Connector {connector_id!r} does not declare streaming support.",
                context={"connector": connector_id},
            )
        await self._ensure_started(connector_id)
        async for item in connector.fetch_stream(request):
            yield item

    async def stop(self, connector_id: str) -> None:
        connector = self.registry.get(connector_id)
        async with self._lock:
            try:
                await connector.stop()
            finally:
                # Connector.stop() clears its own started state even when its
                # cleanup hook fails. Keep the manager's state in sync so a
                # later acquisition does not mistake a closed connector for a
                # live one.
                self._started.discard(connector_id)

    async def stop_all(self) -> None:
        failures: list[tuple[str, Exception]] = []
        for connector_id in sorted(self.registry.names()):
            try:
                await self.stop(connector_id)
            except Exception as exc:
                failures.append((connector_id, exc))
        if failures:
            connector_id, error = failures[0]
            raise ConnectorError(
                f"{len(failures)} connector(s) failed to stop; "
                f"first failure was {connector_id!r}: {error}",
                context={
                    "connectors": [
                        {"connector": name, "error": str(exc)}
                        for name, exc in failures
                    ]
                },
            ) from error

    async def _ensure_started(self, connector_id: str) -> None:
        if connector_id not in self._started:
            await self.start(connector_id)


def _execution_fields(context: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    if context is None:
        return {}
    allowed = {
        "mission_id",
        "investigation_id",
        "task_id",
        "trace_id",
        "tool_id",
        "model_id",
    }
    return {key: context[key] for key in allowed if key in context}
