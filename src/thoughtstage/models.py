"""Typed experiment and event contracts.

Public posts and private soliloquies intentionally use different models. Agent
contexts accept only public posts, making accidental private-channel disclosure
harder than it would be with a single catch-all message type.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Schedule(StrEnum):
    SIMULTANEOUS = "simultaneous"
    SEQUENTIAL = "sequential"


class TurnOrder(StrEnum):
    DECLARED = "declared"
    SEEDED_RANDOM = "seeded_random"


class PrivateMemory(StrEnum):
    NONE = "none"
    OWN_HISTORY = "own_history"


ModelUsagePhase = Literal["combined", "private", "public"]


class AgentConfig(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    display_name: str = Field(min_length=1, max_length=80)
    persona_prompt: str = Field(min_length=1)
    private_briefing: str | None = Field(default=None, min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    credential_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    temperature: float = Field(default=0.7, ge=0, le=2)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ExperimentConfig(StrictModel):
    schema_version: Literal["0.1"] = "0.1"
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    system_prompt: str = Field(min_length=1)
    rounds: int = Field(default=1, ge=1, le=10_000)
    schedule: Schedule = Schedule.SIMULTANEOUS
    turn_order: TurnOrder = TurnOrder.DECLARED
    private_memory: PrivateMemory = PrivateMemory.NONE
    seed: int = 0
    files_dir: str | None = None
    agents: tuple[AgentConfig, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_agent_ids(self) -> ExperimentConfig:
        ids = [agent.id for agent in self.agents]
        if len(ids) != len(set(ids)):
            raise ValueError("agent ids must be unique")
        return self


class PublicPost(StrictModel):
    event_id: str
    sequence: int = Field(ge=1)
    experiment_id: str
    round_number: int = Field(ge=1)
    agent_id: str
    display_name: str
    content: str


class Soliloquy(StrictModel):
    event_id: str
    post_event_id: str
    sequence: int = Field(ge=1)
    experiment_id: str
    round_number: int = Field(ge=1)
    agent_id: str
    content: str


class AgentTurnContext(StrictModel):
    """The complete information boundary passed into a provider adapter."""

    experiment_id: str
    round_number: int
    system_prompt: str
    persona_prompt: str
    private_briefing: str | None = None
    public_feed: tuple[PublicPost, ...]
    own_soliloquies: tuple[str, ...] = ()
    available_files: tuple[str, ...] = ()


class ModelCallUsage(StrictModel):
    phase: ModelUsagePhase
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(ge=0)
    response_id: str | None = Field(default=None, max_length=256)


class ModelUsageEvent(StrictModel):
    event_id: str
    post_event_id: str
    sequence: int = Field(ge=1)
    call_index: int = Field(ge=1)
    experiment_id: str
    round_number: int = Field(ge=1)
    agent_id: str
    provider: str
    model: str
    phase: ModelUsagePhase
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(ge=0)
    response_id: str | None = Field(default=None, max_length=256)


class ModelOutput(StrictModel):
    post: str = Field(min_length=1)
    soliloquy: str = Field(min_length=1)


class ProviderResult(StrictModel):
    output: ModelOutput
    usage: tuple[ModelCallUsage, ...] = ()


class RunResult(StrictModel):
    run_id: str
    bundle_path: str
    public_posts: tuple[PublicPost, ...]
    soliloquies: tuple[Soliloquy, ...]
    model_usage: tuple[ModelUsageEvent, ...] = ()
