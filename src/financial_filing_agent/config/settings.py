import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FFA_", env_file=".env", extra="ignore")
    config_version: str = "1"
    finbert_model: str = "yiyanghkust/finbert-pretrain"
    finbert_revision: str = "88ab954a39ea6d3ce2b62cff086dd5ad1172c664"
    finbert_device: Literal["auto", "cuda", "cpu"] = "auto"
    token_limit: int = Field(default=256, ge=16, le=512)
    batch_size: int = Field(default=16, ge=1, le=128)
    top_k: int = Field(default=5, ge=1, le=50)
    semantic_weight: float = Field(default=1.0, ge=0)
    lexical_weight: float = Field(default=0.25, ge=0)
    xbrl_weight: float = Field(default=0.25, ge=0)
    correction_budget: int = Field(default=2, ge=0, le=4)
    expansion_budget: int = Field(default=1, ge=0, le=1)
    correction_chunk_size: int = Field(default=30, ge=1, le=100)
    max_correction_chunks: int = Field(default=4, ge=1, le=10)
    ollama_url: str = "http://localhost:11434"
    decoder_model: str = "qwen2.5:latest"
    qwen_enabled: bool = True
    expected_decoder_digest: str | None = None
    temperature: float = Field(default=0, ge=0, le=2)
    decoder_timeout: int = Field(default=120, ge=1)
    transport_retries: int = Field(default=1, ge=0, le=3)
    sec_user_agent: str = ""
    artifact_dir: Path = Path("artifacts")
    parser_version: str = "ixbrl-table-v5"
    prompt_version: str = "3"
    formula_version: str = "1"
    decoder_context: int = Field(default=16384, ge=4096, le=131072)
    decoder_output_tokens: int = Field(default=1200, ge=128, le=4096)

    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()

    @classmethod
    def from_file(cls, path):
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))
