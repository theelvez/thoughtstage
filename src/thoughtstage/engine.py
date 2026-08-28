"""Round-based social experiment engine."""

from __future__ import annotations

import random
from collections.abc import Mapping
from pathlib import Path

from thoughtstage.config import LoadedExperiment
from thoughtstage.file_tools import ExperimentFileTools
from thoughtstage.files import ExperimentFileReader
from thoughtstage.models import (
    AgentConfig,
    AgentTurnContext,
    FileToolEvent,
    ModelUsageEvent,
    PrivateMemory,
    PublicPost,
    PublicStimulus,
    RunResult,
    Schedule,
    ScheduledStimulus,
    Soliloquy,
    TurnOrder,
)
from thoughtstage.providers.azure_foundry import AzureFoundryProvider
from thoughtstage.providers.base import Provider
from thoughtstage.providers.bedrock import BedrockProvider
from thoughtstage.providers.mock import MockProvider
from thoughtstage.providers.openai_compatible import OpenAICompatibleProvider
from thoughtstage.reproducibility import RunBundleResumeError, RunBundleWriter


class UnknownProviderError(ValueError):
    pass


class ExperimentEngine:
    def __init__(self, providers: Mapping[str, Provider] | None = None) -> None:
        self.providers: dict[str, Provider] = {
            "azure_foundry": AzureFoundryProvider(),
            "bedrock": BedrockProvider(),
            "mock": MockProvider(),
            "openai_compatible": OpenAICompatibleProvider(),
        }
        if providers:
            self.providers.update(providers)
