"""Deterministic, key-free provider used by examples and contract tests."""

from __future__ import annotations

import hashlib

from thoughtstage.models import AgentConfig, AgentTurnContext, ModelOutput


class MockProvider:
    themes = (
        "define what success means",
        "separate observations from assumptions",
        "invite a falsifiable next step",
        "identify the smallest useful experiment",
        "make disagreement legible",
    )

    def generate(
        self,
        *,
        agent: AgentConfig,
        context: AgentTurnContext,
        seed: int,
    ) -> ModelOutput:
        fingerprint = hashlib.sha256(
            f"{seed}:{context.round_number}:{agent.id}:{len(context.public_feed)}".encode()
        ).digest()
        theme = self.themes[fingerprint[0] % len(self.themes)]
        visible_names = ", ".join(post.display_name for post in context.public_feed) or "no one yet"
        return ModelOutput(
            post=f"I suggest we {theme}. What evidence would change our minds?",
            soliloquy=(
                f"I want {agent.display_name}'s contribution to be concrete without dominating. "
                f"The public feed currently contains posts from {visible_names}."
            ),
        )
