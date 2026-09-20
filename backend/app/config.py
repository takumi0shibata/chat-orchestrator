import os
import re
from functools import lru_cache
from pathlib import Path

import tomllib
import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
IDENTIFIER = r"^[a-zA-Z0-9_-]{1,64}$"


class Folder(BaseModel):
    id: str = Field(pattern=IDENTIFIER)
    label: str
    path: Path

    @model_validator(mode="after")
    def validate_path(self):
        if not self.path.is_absolute() or not self.path.is_dir():
            raise ValueError(f"Folder {self.id} must be an existing absolute directory")
        self.path = self.path.resolve()
        if "," in str(self.path):
            raise ValueError("Docker bind paths cannot contain commas")
        return self


class Skill(Folder):
    name: str = ""
    description: str = ""

    @model_validator(mode="after")
    def read_manifest(self):
        manifests = [p for p in self.path.iterdir() if p.name.lower() == "skill.md"]
        if len(manifests) != 1:
            raise ValueError(f"Skill {self.id} requires one SKILL.md")
        text = manifests[0].read_text(encoding="utf-8")
        match = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|$)", text, re.S)
        meta = yaml.safe_load(match.group(1)) if match else None
        if not isinstance(meta, dict) or not all(
            isinstance(meta.get(k), str) and meta[k].strip()
            for k in ("name", "description")
        ):
            raise ValueError(f"Invalid SKILL.md front matter: {self.id}")
        self.name, self.description = meta["name"], meta["description"]
        return self


class MCPServer(BaseModel):
    id: str = Field(pattern=IDENTIFIER)
    label: str
    url: str
    allowed_tools: list[str]
    authorization_env: str | None = None

    @model_validator(mode="after")
    def validate_server(self):
        if not self.url.startswith("https://") or not self.allowed_tools:
            raise ValueError(
                "Remote MCP requires HTTPS and an explicit nonempty allowed_tools list"
            )
        return self

    def tool(self):
        result = dict(
            type="mcp",
            server_label=self.id,
            server_url=self.url,
            allowed_tools=self.allowed_tools,
            require_approval="always",
        )
        if self.authorization_env:
            secret = os.environ.get(self.authorization_env)
            if not secret:
                raise ValueError(
                    f"Missing MCP credential environment variable: {self.authorization_env}"
                )
            result["authorization"] = secret
        return result


class Deployment(BaseModel):
    model: str
    deployment: str


class RuntimeConfig(BaseModel):
    project_doc_max_bytes: int = Field(default=32 * 1024, ge=1)
    project_doc_fallback_filenames: list[str] = Field(default_factory=list)
    workspaces: list[Folder] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    resources: list[Folder] = Field(default_factory=list)
    mcp_servers: list[MCPServer] = Field(default_factory=list)
    azure_models: list[Deployment] = Field(default_factory=list)

    @field_validator("project_doc_fallback_filenames")
    @classmethod
    def validate_project_doc_fallbacks(cls, names):
        reserved = {"AGENTS.override.md", "AGENTS.md"}
        if len(set(names)) != len(names):
            raise ValueError("Project instruction fallback filenames must be unique")
        for name in names:
            if (
                not name.strip()
                or not name.isprintable()
                or name in (".", "..")
                or "/" in name
                or "\\" in name
                or name in reserved
            ):
                raise ValueError(
                    "Project instruction fallback filenames must be unique basenames"
                )
        return names

    @model_validator(mode="after")
    def unique_ids(self):
        for group in (self.workspaces, self.skills, self.resources, self.mcp_servers):
            if len({x.id for x in group}) != len(group):
                raise ValueError("Duplicate configuration IDs")
        # Parent/child mounts would bypass same-workspace serialization.
        for i, folder in enumerate(self.workspaces):
            for other in self.workspaces[i + 1 :]:
                if folder.path.is_relative_to(other.path) or other.path.is_relative_to(
                    folder.path
                ):
                    raise ValueError("Workspace directories must not overlap")
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(ROOT / "backend/.env"), str(ROOT / ".env")), extra="ignore"
    )
    openai_api_key: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_endpoint: str | None = None
    http_proxy: str | None = None
    https_proxy: str | None = None
    all_proxy: str | None = None
    no_proxy: str | None = None
    runtime_config: Path = ROOT / "runtime.toml"
    data_dir: Path = ROOT / "backend/data/agent"
    sandbox_image: str = "chat-orchestrator-sandbox:local"
    sandbox_cpus: float = Field(default=4, gt=0)
    sandbox_memory: str = "8g"
    sandbox_pids: int = Field(default=256, ge=32)
    command_timeout: int = Field(default=600, ge=1)
    command_timeout_min: int = Field(default=60, ge=1)
    run_timeout: int = Field(default=3600, ge=1)
    max_model_rounds: int = Field(default=100, ge=1)
    max_output_chars: int = Field(default=64000, ge=1024)
    compact_token_threshold: int = Field(default=100000, ge=1000)
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1)

    @property
    def outbound_proxy_url(self):
        return next(
            (
                x.strip()
                for x in (self.all_proxy, self.https_proxy, self.http_proxy)
                if x and x.strip()
            ),
            None,
        )

    @property
    def azure_openai_base_url(self):
        endpoint = (self.azure_openai_endpoint or "").rstrip("/")
        return endpoint if endpoint.endswith("/openai/v1") else endpoint + "/openai/v1"

    def load_runtime(self):
        if not self.runtime_config.exists():
            return RuntimeConfig()
        return RuntimeConfig.model_validate(
            tomllib.loads(self.runtime_config.read_text())
        )


@lru_cache
def get_settings():
    return Settings()
