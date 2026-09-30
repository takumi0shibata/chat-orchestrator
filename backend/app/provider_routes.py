"""Resolve model selections to immutable, backend-only provider connections."""

import logging
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.model_catalog import models_for

log = logging.getLogger(__name__)


def azure_base_url(endpoint, connection_id):
    endpoint = endpoint.strip().rstrip("/")
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.username or parsed.password or parsed.query or parsed.fragment
        or parsed.path not in ("", "/openai/v1")
    ):
        raise ValueError(f"Invalid Azure Endpoint for connection {connection_id}")
    # Accessing port also validates malformed port numbers without displaying the URL.
    try:
        parsed.port
    except ValueError:
        raise ValueError(f"Invalid Azure Endpoint for connection {connection_id}") from None
    resource = f"https://{parsed.netloc.lower()}"
    return resource + "/openai/v1"


@dataclass(frozen=True)
class Connection:
    id: str
    label: str
    base_url: str | None = field(repr=False)
    api_key: str | None = field(repr=False)


@dataclass(frozen=True)
class ModelRoute:
    connection: Connection
    deployment: str


class ProviderRoutes:
    def __init__(self, settings, config, *, allow_unconfigured=False):
        self.config = config
        self.allow_unconfigured = allow_unconfigured
        self.openai = Connection("openai", "OpenAI", None, settings.openai_api_key)
        self.azure = {}
        entries = [("default", "既存Azure", settings.azure_openai_endpoint,
                    settings.azure_openai_api_key, "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY")]
        entries += [
            (c.id, c.label, settings.credential_env(c.endpoint_env),
             settings.credential_env(c.api_key_env), c.endpoint_env, c.api_key_env)
            for c in config.azure_connections
        ]
        for cid, label, endpoint, key, endpoint_env, key_env in entries:
            try:
                base_url = azure_base_url(endpoint, cid) if endpoint and endpoint.strip() else ""
            except ValueError:
                raise ValueError(f"Invalid Azure Endpoint: connection {cid}, variable {endpoint_env}") from None
            key = key.strip() if key else None
            self.azure[cid] = Connection(cid, label, base_url, key)
            missing = [name for name, value in ((endpoint_env, base_url), (key_env, key)) if not value]
            if missing and any(d.connection_id == cid for d in config.azure_models):
                log.warning("Azure connection %s unavailable: configure %s", cid, ", ".join(missing))

    def available(self, connection):
        return self.allow_unconfigured or bool(
            connection.api_key and (connection is self.openai or connection.base_url)
        )

    def models(self, provider):
        catalog = models_for(provider, self.config)
        if provider == "openai":
            return catalog if self.available(self.openai) else []
        result = []
        for item in catalog:
            deployment = next(d for d in self.config.azure_models if d.selection_id == item["id"])
            connection = self.azure[deployment.connection_id]
            if self.available(connection):
                result.append(dict(**item, deployment=deployment.deployment,
                                   connection_id=connection.id, connection_label=connection.label))
        return result

    def resolve(self, provider, model):
        if not any(m["id"] == model for m in self.models(provider)):
            raise ValueError("Unsupported or unavailable model/deployment")
        if provider == "openai":
            return ModelRoute(self.openai, model)
        deployment = next(d for d in self.config.azure_models if d.selection_id == model)
        return ModelRoute(self.azure[deployment.connection_id], deployment.deployment)

    def secrets(self):
        return [c.api_key for c in [self.openai, *self.azure.values()] if c.api_key]
