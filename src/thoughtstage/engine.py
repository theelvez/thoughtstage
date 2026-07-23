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
from thoughtstage.reproducibility import RunBundleResumeError, RunBundleWriter


class UnknownProviderError(ValueError):
    pass


class ExperimentEngine:
    def __init__(self, providers: Mapping[str, Provider] | None = None) -> None:
        self.providers: dict[str, Provider] = {
            "azure_foundry": AzureFoundryProvider(),
            "bedrock": BedrockProvider(),
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
    def _stimulus_event(
        *,
        stimulus: ScheduledStimulus,
        experiment_id: str,
        sequence: int,
    ) -> PublicStimulus:
        return PublicStimulus(
            event_id=f"stimulus-r{stimulus.round:04d}-{stimulus.id}-{sequence:06d}",
            sequence=sequence,
            experiment_id=experiment_id,
            round_number=stimulus.round,
            stimulus_id=stimulus.id,
            source_id=stimulus.source_id,
            display_name=stimulus.display_name,
            content=stimulus.content,
        )

    @staticmethod
    def _validate_replayed_stimulus(
        *,
        actual: PublicStimulus,
        expected: PublicStimulus,
    ) -> None:
        if actual != expected:
            raise RunBundleResumeError(
                "existing public stimulus prefix does not match the experiment"
            )

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

    @staticmethod
    def _validate_replayed_file_tools(
        events: list[FileToolEvent],
        posts: list[PublicPost],
        agents: tuple[AgentConfig, ...],
    ) -> None:
        posts_by_id = {post.event_id: post for post in posts}
        agents_by_id = {agent.id: agent for agent in agents}
        event_ids: set[str] = set()
        tool_indexes: dict[str, set[int]] = {}
        for item in events:
            post = posts_by_id.get(item.post_event_id)
            agent = agents_by_id.get(item.agent_id)
            if post is None or agent is None:
                raise RunBundleResumeError(
                    "existing file tool event does not match the run event prefix"
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
            indexes = tool_indexes.setdefault(item.post_event_id, set())
            if item.event_id in event_ids or item.tool_index in indexes or actual != expected:
                raise RunBundleResumeError(
                    "existing file tool event does not match the run event prefix"
                )
            event_ids.add(item.event_id)
            indexes.add(item.tool_index)
        if any(
            sorted(indexes) != list(range(1, len(indexes) + 1)) for indexes in tool_indexes.values()
        ):
            raise RunBundleResumeError("existing file tool indexes are not contiguous")

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
            existing_stimuli: list[PublicStimulus] = []
            existing_model_usage: list[ModelUsageEvent] = []
            existing_file_tool_events: list[FileToolEvent] = []
        else:
            writer = RunBundleWriter.resume(loaded, resume_path)
            existing_posts, existing_soliloquies = writer.existing_events()
            existing_stimuli = writer.existing_stimuli()
            existing_model_usage = writer.existing_model_usage()
            existing_file_tool_events = writer.existing_file_tool_events()
        self._validate_replayed_usage(existing_model_usage, existing_posts, config.agents)
        self._validate_replayed_file_tools(existing_file_tool_events, existing_posts, config.agents)
        public_posts: list[PublicPost] = []
        public_stimuli: list[PublicStimulus] = []
        public_feed: list[PublicPost | PublicStimulus] = []
        soliloquies: list[Soliloquy] = []
        model_usage: list[ModelUsageEvent] = list(existing_model_usage)
        file_tool_events: list[FileToolEvent] = list(existing_file_tool_events)
        private_by_agent: dict[str, list[str]] = {agent.id: [] for agent in config.agents}
        available_files = tuple(item["path"] for item in writer.files)
        file_tools = (
            ExperimentFileTools(ExperimentFileReader(loaded.files_root))
            if loaded.files_root is not None
            else None
        )
        replay_index = 0
        stimulus_replay_index = 0
        stimuli_by_round: dict[int, list[ScheduledStimulus]] = {}
        for stimulus in config.stimuli:
            stimuli_by_round.setdefault(stimulus.round, []).append(stimulus)

        for round_number in range(1, config.rounds + 1):
            for scheduled in stimuli_by_round.get(round_number, []):
                expected_stimulus = self._stimulus_event(
                    stimulus=scheduled,
                    experiment_id=config.id,
                    sequence=len(public_feed) + 1,
                )
                if stimulus_replay_index < len(existing_stimuli):
                    stimulus = existing_stimuli[stimulus_replay_index]
                    self._validate_replayed_stimulus(
                        actual=stimulus,
                        expected=expected_stimulus,
                    )
                    stimulus_replay_index += 1
                else:
                    if replay_index < len(existing_posts):
                        raise RunBundleResumeError(
                            "run bundle is missing a scheduled public stimulus"
                        )
                    stimulus = expected_stimulus
                    writer.write_stimulus(stimulus)
                public_stimuli.append(stimulus)
                public_feed.append(stimulus)

            round_start_feed = tuple(public_feed)
            pending_posts: list[PublicPost] = []
            pending_soliloquies: list[Soliloquy] = []
            pending_generated: list[bool] = []
            pending_usage: list[tuple[ModelUsageEvent, ...]] = []
            pending_file_tools: list[tuple[FileToolEvent, ...]] = []
            ordered_agents = self._order_agents(
                config.agents, config.turn_order, config.seed, round_number
            )

            for agent in ordered_agents:
                sequence = len(public_feed) + len(pending_posts) + 1
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
                        pending_file_tools.append(())
                    else:
                        public_posts.append(post)
                        public_feed.append(post)
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
                    else tuple(public_feed)
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
                    private_briefing=agent.private_briefing,
                    public_feed=feed,
                    own_soliloquies=own_history,
                    available_files=available_files,
                )
                provider_result = provider.generate(
                    agent=agent,
                    context=context,
                    seed=config.seed,
                    file_tools=file_tools,
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
                tool_events = tuple(
                    FileToolEvent(
                        **item.model_dump(),
                        event_id=(
                            f"file-tool-r{round_number:04d}-{agent.id}-"
                            f"{sequence:06d}-tool{tool_index:02d}"
                        ),
                        post_event_id=post_event_id,
                        sequence=sequence,
                        tool_index=tool_index,
                        experiment_id=config.id,
                        round_number=round_number,
                        agent_id=agent.id,
                        provider=agent.provider,
                        model=agent.model,
                    )
                    for tool_index, item in enumerate(provider_result.file_tool_calls, start=1)
                )

                private_by_agent[agent.id].append(output.soliloquy)
                if config.schedule is Schedule.SIMULTANEOUS:
                    pending_posts.append(post)
                    pending_soliloquies.append(soliloquy)
                    pending_generated.append(True)
                    pending_usage.append(usage_events)
                    pending_file_tools.append(tool_events)
                else:
                    public_posts.append(post)
                    public_feed.append(post)
                    soliloquies.append(soliloquy)
                    writer.write_post(post)
                    writer.write_soliloquy(soliloquy)
                    model_usage.extend(usage_events)
                    for item in usage_events:
                        writer.write_model_usage(item)
                    file_tool_events.extend(tool_events)
                    for item in tool_events:
                        writer.write_file_tool_event(item)

            if config.schedule is Schedule.SIMULTANEOUS:
                for post, soliloquy, usage_events, tool_events, generated in zip(
                    pending_posts,
                    pending_soliloquies,
                    pending_usage,
                    pending_file_tools,
                    pending_generated,
                    strict=True,
                ):
                    public_posts.append(post)
                    public_feed.append(post)
                    soliloquies.append(soliloquy)
                    model_usage.extend(usage_events)
                    file_tool_events.extend(tool_events)
                    if generated:
                        writer.write_post(post)
                        writer.write_soliloquy(soliloquy)
                        for item in usage_events:
                            writer.write_model_usage(item)
                        for item in tool_events:
                            writer.write_file_tool_event(item)

        if replay_index != len(existing_posts):
            raise RunBundleResumeError(
                "run bundle contains more events than the experiment declares"
            )
        if stimulus_replay_index != len(existing_stimuli):
            raise RunBundleResumeError(
                "run bundle contains more public stimuli than the experiment declares"
            )

        writer.finish(
            public_posts=len(public_posts),
            public_stimuli=len(public_stimuli),
            soliloquies=len(soliloquies),
            model_calls=len(model_usage),
            file_tool_calls=len(file_tool_events),
        )
        return RunResult(
            run_id=writer.run_id,
            bundle_path=str(writer.path),
            public_posts=tuple(public_posts),
            public_stimuli=tuple(public_stimuli),
            soliloquies=tuple(soliloquies),
            model_usage=tuple(model_usage),
            file_tool_events=tuple(file_tool_events),
        )
