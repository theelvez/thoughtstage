"""Provider adapter contract."""

from __future__ import annotations

from typing import Protocol

from thoughtstage.file_tools import ExperimentFileTools
from thoughtstage.models import AgentConfig, AgentTurnContext, ProviderResult


class Provider(Protocol):
    """Translate a safe agent context into the platform's dual output."""

    def generate(
        self,
        *,
        agent: AgentConfig,
        context: AgentTurnContext,
        seed: int,
        file_tools: ExperimentFileTools | None = None,
    ) -> ProviderResult: ...
