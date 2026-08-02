"""In-process metrics registry with Prometheus text exposition."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricsRegistry:
    """Thread-safe counters, gauges and latency histograms for unit tests and API."""

    counters: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    gauges: dict[str, float] = field(default_factory=dict)
    histograms: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def incr(
        self,
        name: str,
        amount: float = 1.0,
        *,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        key = _metric_key(name, labels)
        with self._lock:
            self.counters[key] += amount

    def set_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        key = _metric_key(name, labels)
        with self._lock:
            self.gauges[key] = value

    def observe(
        self,
        name: str,
        value_seconds: float,
        *,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        key = _metric_key(name, labels)
        with self._lock:
            self.histograms[key].append(value_seconds)

    @contextmanager
    def timer(self, name: str, *, labels: Mapping[str, str] | None = None) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.observe(name, time.perf_counter() - started, labels=labels)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            hist_summary = {
                name: {
                    "count": len(values),
                    "sum": sum(values),
                    "avg": (sum(values) / len(values)) if values else 0.0,
                }
                for name, values in self.histograms.items()
            }
            return {
                "counters": dict(self.counters),
                "gauges": dict(self.gauges),
                "histograms": hist_summary,
            }

    def as_flat_counters(self) -> dict[str, int]:
        """Backward-compatible flat int map for simple API clients."""
        with self._lock:
            flat: dict[str, int] = {name: int(value) for name, value in self.counters.items()}
            for name, value in self.gauges.items():
                flat[f"gauge_{name}"] = int(value)
            return flat

    def render_prometheus(self) -> str:
        """Render Prometheus text exposition without mutating global collectors."""
        lines: list[str] = []
        with self._lock:
            for name, value in sorted(self.counters.items()):
                metric, labels = _parse_metric_key(name)
                lines.append(f"# TYPE {metric} counter")
                lines.append(f"{metric}{_label_text(labels)} {value}")
            for name, value in sorted(self.gauges.items()):
                metric, labels = _parse_metric_key(name)
                lines.append(f"# TYPE {metric} gauge")
                lines.append(f"{metric}{_label_text(labels)} {value}")
            for name, values in sorted(self.histograms.items()):
                metric, labels = _parse_metric_key(name)
                label_text = _label_text(labels)
                count = len(values)
                total = sum(values)
                lines.append(f"# TYPE {metric} summary")
                lines.append(f"{metric}_count{label_text} {count}")
                lines.append(f"{metric}_sum{label_text} {total}")
        return "\n".join(lines) + ("\n" if lines else "")


_DEFAULT_REGISTRY = MetricsRegistry()


def get_metrics() -> MetricsRegistry:
    return _DEFAULT_REGISTRY


def reset_metrics() -> None:
    registry = get_metrics()
    with registry._lock:
        registry.counters.clear()
        registry.gauges.clear()
        registry.histograms.clear()


def _metric_key(name: str, labels: Mapping[str, str] | None) -> str:
    if not labels:
        return name
    parts = ",".join(f"{key}={labels[key]}" for key in sorted(labels))
    return f"{name}{{{parts}}}"


def _parse_metric_key(key: str) -> tuple[str, dict[str, str]]:
    if "{" not in key or not key.endswith("}"):
        return _prom_name(key), {}
    name, raw = key[:-1].split("{", 1)
    labels: dict[str, str] = {}
    for part in raw.split(","):
        if "=" not in part:
            continue
        label_key, label_value = part.split("=", 1)
        labels[label_key] = label_value
    return _prom_name(name), labels


def _prom_name(name: str) -> str:
    return name.replace(".", "_").replace("-", "_")


def _label_text(labels: Mapping[str, str]) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{key}="{value}"' for key, value in sorted(labels.items()))
    return "{" + inner + "}"


__all__ = ["MetricsRegistry", "get_metrics", "reset_metrics"]
