"""Configuration from the environment. Nothing else is read, and no secret has a default."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from oncall_responder.evidence import base
from oncall_responder.incident import origin
from oncall_responder.model import MODELS
from oncall_responder.signing import MIN_SECRET


class SettingsError(Exception):
    """A setting is missing or unusable. The message never contains a value."""


@dataclass(frozen=True)
class Settings:
    secret: str
    model: str
    prometheus_url: str
    loki_url: str
    tempo_url: str
    grafana_origin: str | None
    reports_file: Path

    @property
    def secrets(self) -> tuple[str, ...]:
        """Exact values scrubbed from anything the responder prompts with, stores or logs."""
        return (self.secret,)

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Settings":
        secret = env.get("ONCALL_HMAC_SECRET", "")
        if len(secret) < MIN_SECRET:
            raise SettingsError(f"ONCALL_HMAC_SECRET must be set, at least {MIN_SECRET} characters")
        model = env.get("ONCALL_MODEL", "fake")
        if model not in MODELS:
            raise SettingsError(f"ONCALL_MODEL must be one of {sorted(MODELS)}")
        urls = {}
        for name in ("PROMETHEUS_URL", "LOKI_URL", "TEMPO_URL"):
            try:
                base(env.get(name, ""))
            except ValueError:
                raise SettingsError(f"{name} must look like http://host:port") from None
            urls[name] = env[name]
        grafana = env.get("ONCALL_GRAFANA_ORIGIN") or None
        if grafana is not None and origin(grafana) != grafana:
            raise SettingsError("ONCALL_GRAFANA_ORIGIN must be an origin like http://host:port")
        return cls(
            secret=secret,
            model=model,
            prometheus_url=urls["PROMETHEUS_URL"],
            loki_url=urls["LOKI_URL"],
            tempo_url=urls["TEMPO_URL"],
            grafana_origin=grafana,
            reports_file=Path(env.get("ONCALL_REPORTS", "/var/lib/oncall/reports.jsonl")),
        )
