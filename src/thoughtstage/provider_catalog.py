"""Researcher-only model catalogs for the experiment builder.

Listing is presence-only: environment-variable names may appear in error text,
but endpoint URLs, profile values, tokens, and keys never leave this module.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from thoughtstage.models import StrictModel

ProviderName = Literal["azure_foundry", "bedrock", "mock", "openai_compatible"]
CatalogSource = Literal["builtin", "endpoint"]

NON_CHAT_MARKERS = (
    "embedding",
    "embed-",
    "-embed",
    "whisper",
    "tts-",
    "-tts",
    "dall-e",
    "dalle",
    "image-generation",
    "moderation",
    "text-to-speech",
    "speech-to-text",
)


class CatalogModel(StrictModel):
    """One selectable model or deployment name."""

    id: str = Field(min_length=1, max_length=256)
    label: str = Field(min_length=1, max_length=320)


class ProviderModelQuery(StrictModel):
    """Researcher request to list models for one provider binding."""

    provider: ProviderName
    region: str | None = Field(default=None, max_length=32)
    credential_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    endpoint_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    base_url_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")

    @field_validator("region")
    @classmethod
    def validate_region(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        trimmed = value.strip()
        if not trimmed.replace("-", "").isalnum() or not trimmed.islower():
            raise ValueError("region must be a lowercase AWS Region id")
        return trimmed


class ProviderModelCatalog(StrictModel):
    """Catalog payload safe to return to the researcher dashboard."""

    provider: ProviderName
    ok: bool
    source: CatalogSource
    models: tuple[CatalogModel, ...] = ()
    error: str | None = None
    missing: tuple[str, ...] = ()


def catalog_model(model_id: str, label: str | None = None) -> CatalogModel:
    trimmed = model_id.strip()
    return CatalogModel(id=trimmed, label=(label or trimmed).strip() or trimmed)


def looks_like_non_chat(model_id: str, *extra: str) -> bool:
    haystack = " ".join(part for part in (model_id, *extra) if part).lower()
    return any(marker in haystack for marker in NON_CHAT_MARKERS)


def empty_catalog(
    provider: ProviderName,
    *,
    source: CatalogSource,
    error: str,
    missing: tuple[str, ...] = (),
) -> ProviderModelCatalog:
    return ProviderModelCatalog(
        provider=provider,
        ok=False,
        source=source,
        models=(),
        error=error,
        missing=missing,
    )


def success_catalog(
    provider: ProviderName,
    *,
    source: CatalogSource,
    models: list[CatalogModel],
) -> ProviderModelCatalog:
    unique: dict[str, CatalogModel] = {}
    for model in models:
        unique.setdefault(model.id, model)
    return ProviderModelCatalog(
        provider=provider,
        ok=True,
        source=source,
        models=tuple(sorted(unique.values(), key=lambda item: item.id.lower())),
        error=None,
        missing=(),
    )


def list_provider_models(query: ProviderModelQuery) -> ProviderModelCatalog:
    """Dispatch a catalog request to the selected provider adapter."""

    if query.provider == "mock":
        from thoughtstage.providers.mock import MockProvider

        return MockProvider().list_models()
    if query.provider == "azure_foundry":
        from thoughtstage.providers.azure_foundry import AzureFoundryProvider

        return AzureFoundryProvider().list_models(
            endpoint_env=query.endpoint_env,
            credential_env=query.credential_env,
        )
    if query.provider == "bedrock":
        from thoughtstage.providers.bedrock import BedrockProvider

        return BedrockProvider().list_models(
            region=query.region,
            credential_env=query.credential_env,
        )
    from thoughtstage.providers.openai_compatible import OpenAICompatibleProvider

    return OpenAICompatibleProvider().list_models(
        base_url_env=query.base_url_env,
        credential_env=query.credential_env,
    )
