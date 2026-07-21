"""Round-based social experiment engine."""

from __future__ import annotations

import random
from collections.abc import Mapping
from pathlib import Path

from thoughtstage.config import LoadedExperiment
from thoughtstage.models import (
    AgentConfig,
    AgentTurnContext,
    ModelUsageEvent,
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
from thoughtstage.reproducibility import RunBundleResumeError, RunBundleWriter


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

    @staticmethod
    def _validate_replayed_turn(
        *,
        post: PublicPost,
        soliloquy: Soliloquy,
        agent: AgentConfig,
        experiment_id: str,
        round_number: int,
        sequence: int,
    ) -> None:
        expected = (experiment_id, round_number, agent.id, sequence)
        actual_post = (post.experiment_id, post.round_number, post.agent_id, post.sequence)
        actual_private = (
            soliloquy.experiment_id,
            soliloquy.round_number,
            soliloquy.agent_id,
            soliloquy.sequence,
        )
        if actual_post != expected or actual_private != expected:
            raise RunBundleResumeError("existing run event prefix does not match the experiment")
        if soliloquy.post_event_id != post.event_id:
            raise RunBundleResumeError("existing private event does not match its public post")

    @staticmethod
    def _validate_replayed_usage(
        usage: list[ModelUsageEvent],
        posts: list[PublicPost],
        agents: tuple[AgentConfig, ...],
    ) -> None:
        posts_by_id = {post.event_id: post for post in posts}
        agents_by_id = {agent.id: agent for agent in agents}
        event_ids: set[str] = set()
        call_indexes: dict[str, set[int]] = {}
        for item in usage:
            post = posts_by_id.get(item.post_event_id)
            agent = agents_by_id.get(item.agent_id)
            if post is None or agent is None:
                raise RunBundleResumeError(
                    "existing model usage does not match the run event prefix"
                )
            expected = (
                post.experiment_id,
                post.round_number,
                post.agent_id,
                post.sequence,
                agent.provider,
                agent.model,
            )
            actual = (
                item.experiment_id,
                item.round_number,
                item.agent_id,
                item.sequence,
                item.provider,
                item.model,
            )
            indexes = call_indexes.setdefault(item.post_event_id, set())
            if item.event_id in event_ids or item.call_index in indexes or actual != expected:
                raise RunBundleResumeError(
                    "existing model usage does not match the run event prefix"
                )
            event_ids.add(item.event_id)
            indexes.add(item.call_index)
        if any(
            sorted(indexes) != list(range(1, len(indexes) + 1)) for indexes in call_indexes.values()
        ):
            raise RunBundleResumeError("existing model usage call indexes are not contiguous")

    def run(
        self,
        loaded: LoadedExperiment,
        *,
        output_root: str | Path = "runs",
        run_id: str | None = None,
        resume_path: str | Path | None = None,
    ) -> RunResult:
        config = loaded.config
        if resume_path is None:
            writer = RunBundleWriter(loaded, output_root, run_id=run_id)
            existing_posts: list[PublicPost] = []
            existing_soliloquies: list[Soliloquy] = []
            existing_model_usage: list[ModelUsageEvent] = []
        else:
            writer = RunBundleWriter.resume(loaded, resume_path)
            existing_posts, existing_soliloquies = writer.existing_events()
            existing_model_usage = writer.existing_model_usage()
        self._validate_replayed_usage(existing_model_usage, existing_posts, config.agents)
        public_posts: list[PublicPost] = []
        soliloquies: list[Soliloquy] = []
        model_usage: list[ModelUsageEvent] = list(existing_model_usage)
        private_by_agent: dict[str, list[str]] = {agent.id: [] for agent in config.agents}
        available_files = tuple(item["path"] for item in writer.files)
        replay_index = 0

        for round_number in range(1, config.rounds + 1):
            round_start_feed = tuple(public_posts)
            pending_posts: list[PublicPost] = []
            pending_soliloquies: list[Soliloquy] = []
            pending_generated: list[bool] = []
            pending_usage: list[tuple[ModelUsageEvent, ...]] = []
            ordered_agents = self._order_agents(
                config.agents, config.turn_order, config.seed, round_number
            )

            for agent in ordered_agents:
                sequence = len(public_posts) + len(pending_posts) + 1
                if replay_index < len(existing_posts):
                    post = existing_posts[replay_index]
                    soliloquy = existing_soliloquies[replay_index]
                    self._validate_replayed_turn(
                        post=post,
                        soliloquy=soliloquy,
                        agent=agent,
                        experiment_id=config.id,
                        round_number=round_number,
                        sequence=sequence,
                    )
                    replay_index += 1
                    private_by_agent[agent.id].append(soliloquy.content)
                    if config.schedule is Schedule.SIMULTANEOUS:
                        pending_posts.append(post)
                        pending_soliloquies.append(soliloquy)
                        pending_generated.append(False)
                        pending_usage.append(())
                    else:
                        public_posts.append(post)
                        soliloquies.append(soliloquy)
                    continue

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
                provider_result = provider.generate(
                    agent=agent,
                    context=context,
                    seed=config.seed,
                )
                output = provider_result.output
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
                usage_events = tuple(
                    ModelUsageEvent(
                        event_id=(
                            f"usage-r{round_number:04d}-{agent.id}-"
                            f"{sequence:06d}-call{call_index:02d}"
                        ),
                        post_event_id=post_event_id,
                        sequence=sequence,
                        call_index=call_index,
                        experiment_id=config.id,
                        round_number=round_number,
                        agent_id=agent.id,
                        provider=agent.provider,
                        model=agent.model,
                        phase=item.phase,
                        input_tokens=item.input_tokens,
                        cached_input_tokens=item.cached_input_tokens,
                        cache_write_tokens=item.cache_write_tokens,
                        output_tokens=item.output_tokens,
                        reasoning_tokens=item.reasoning_tokens,
                        total_tokens=item.total_tokens,
                        response_id=item.response_id,
                    )
                    for call_index, item in enumerate(provider_result.usage, start=1)
                )

                private_by_agent[agent.id].append(output.soliloquy)
                if config.schedule is Schedule.SIMULTANEOUS:
                    pending_posts.append(post)
                    pending_soliloquies.append(soliloquy)
                    pending_generated.append(True)
                    pending_usage.append(usage_events)
                else:
                    public_posts.append(post)
                    soliloquies.append(soliloquy)
                    writer.write_post(post)
                    writer.write_soliloquy(soliloquy)
                    model_usage.extend(usage_events)
                    for item in usage_events:
                        writer.write_model_usage(item)

            if config.schedule is Schedule.SIMULTANEOUS:
                for post, soliloquy, usage_events, generated in zip(
                    pending_posts,
                    pending_soliloquies,
                    pending_usage,
                    pending_generated,
                    strict=True,
                ):
                    public_posts.append(post)
                    soliloquies.append(soliloquy)
                    model_usage.extend(usage_events)
                    if generated:
                        writer.write_post(post)
                        writer.write_soliloquy(soliloquy)
                        for item in usage_events:
                            writer.write_model_usage(item)

        if replay_index != len(existing_posts):
            raise RunBundleResumeError(
                "run bundle contains more events than the experiment declares"
            )

        writer.finish(
            public_posts=len(public_posts),
            soliloquies=len(soliloquies),
            model_calls=len(model_usage),
        )
        return RunResult(
            run_id=writer.run_id,
            bundle_path=str(writer.path),
            public_posts=tuple(public_posts),
            soliloquies=tuple(soliloquies),
            model_usage=tuple(model_usage),
        )
