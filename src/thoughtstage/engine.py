"""Round-based social experiment engine."""

from __future__ import annotations

import random
from collections.abc import Mapping
from pathlib import Path

from thoughtstage.config import LoadedExperiment
from thoughtstage.models import (
    AgentConfig,
    AgentTurnContext,
    PrivateMemory,
    PublicPost,
    RunResult,
    Schedule,
    Soliloquy,
    TurnOrder,
)
from thoughtstage.providers.azure_foundry import AzureFoundryProvider
from thoughtstage.providers.base import Provider
from thoughtstage.providers.mock import MockProvider
from thoughtstage.reproducibility import RunBundleWriter


class UnknownProviderError(ValueError):
    pass


class ExperimentEngine:
    def __init__(self, providers: Mapping[str, Provider] | None = None) -> None:
        self.providers: dict[str, Provider] = {
            "azure_foundry": AzureFoundryProvider(),
            "mock": MockProvider(),
        }
        if providers:
            self.providers.update(providers)

    def _order_agents(
        self, agents: tuple[AgentConfig, ...], turn_order: TurnOrder, seed: int, round_number: int
    ) -> list[AgentConfig]:
        ordered = list(agents)
        if turn_order is TurnOrder.SEEDED_RANDOM:
            random.Random(seed + round_number).shuffle(ordered)
        return ordered

    def run(
        self,
        loaded: LoadedExperiment,
        *,
        output_root: str | Path = "runs",
        run_id: str | None = None,
    ) -> RunResult:
        config = loaded.config
        writer = RunBundleWriter(loaded, output_root, run_id=run_id)
        public_posts: list[PublicPost] = []
        soliloquies: list[Soliloquy] = []
        private_by_agent: dict[str, list[str]] = {agent.id: [] for agent in config.agents}
        available_files = tuple(item["path"] for item in writer.files)

        for round_number in range(1, config.rounds + 1):
            round_start_feed = tuple(public_posts)
            pending_posts: list[PublicPost] = []
            pending_soliloquies: list[Soliloquy] = []
            ordered_agents = self._order_agents(
                config.agents, config.turn_order, config.seed, round_number
            )

            for agent in ordered_agents:
                provider = self.providers.get(agent.provider)
                if provider is None:
                    raise UnknownProviderError(
                        f"provider {agent.provider!r} is not installed for agent {agent.id!r}"
                    )
                feed = (
                    round_start_feed
                    if config.schedule is Schedule.SIMULTANEOUS
                    else tuple(public_posts)
                )
                own_history = (
                    tuple(private_by_agent[agent.id])
                    if config.private_memory is PrivateMemory.OWN_HISTORY
                    else ()
                )
                context = AgentTurnContext(
                    experiment_id=config.id,
                    round_number=round_number,
                    system_prompt=config.system_prompt,
                    persona_prompt=agent.persona_prompt,
                    public_feed=feed,
                    own_soliloquies=own_history,
                    available_files=available_files,
                )
                output = provider.generate(
                    agent=agent,
                    context=context,
                    seed=config.seed,
                )
                sequence = len(public_posts) + len(pending_posts) + 1
                post_event_id = f"post-r{round_number:04d}-{agent.id}-{sequence:06d}"
                post = PublicPost(
                    event_id=post_event_id,
                    sequence=sequence,
                    experiment_id=config.id,
                    round_number=round_number,
                    agent_id=agent.id,
                    display_name=agent.display_name,
                    content=output.post,
                )
                soliloquy = Soliloquy(
                    event_id=f"soliloquy-r{round_number:04d}-{agent.id}-{sequence:06d}",
                    post_event_id=post_event_id,
                    sequence=sequence,
                    experiment_id=config.id,
                    round_number=round_number,
                    agent_id=agent.id,
                    content=output.soliloquy,
                )

                private_by_agent[agent.id].append(output.soliloquy)
                if config.schedule is Schedule.SIMULTANEOUS:
                    pending_posts.append(post)
                    pending_soliloquies.append(soliloquy)
                else:
                    public_posts.append(post)
                    soliloquies.append(soliloquy)
                    writer.write_post(post)
                    writer.write_soliloquy(soliloquy)

            if config.schedule is Schedule.SIMULTANEOUS:
                for post, soliloquy in zip(pending_posts, pending_soliloquies, strict=True):
                    public_posts.append(post)
                    soliloquies.append(soliloquy)
                    writer.write_post(post)
                    writer.write_soliloquy(soliloquy)

        writer.finish(public_posts=len(public_posts), soliloquies=len(soliloquies))
        return RunResult(
            run_id=writer.run_id,
            bundle_path=str(writer.path),
            public_posts=tuple(public_posts),
            soliloquies=tuple(soliloquies),
        )
