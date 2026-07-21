from thoughtstage.usage import summarize_model_usage


def test_usage_summary_aggregates_calls_by_research_dimensions() -> None:
    records = [
        {
            "agent_id": "atlas",
            "provider": "azure_foundry",
            "model": "gpt-4o",
            "phase": "combined",
            "input_tokens": 100,
            "cached_input_tokens": 20,
            "cache_write_tokens": 0,
            "output_tokens": 30,
            "reasoning_tokens": 5,
            "total_tokens": 130,
        },
        {
            "agent_id": "ember",
            "provider": "azure_foundry",
            "model": "DeepSeek-V3.2",
            "phase": "private",
            "input_tokens": 80,
            "cached_input_tokens": 0,
            "cache_write_tokens": 10,
            "output_tokens": 20,
            "reasoning_tokens": 0,
            "total_tokens": 100,
        },
    ]

    summary = summarize_model_usage(records)

    assert summary["totals"] == {
        "model_calls": 2,
        "input_tokens": 180,
        "cached_input_tokens": 20,
        "cache_write_tokens": 10,
        "output_tokens": 50,
        "reasoning_tokens": 5,
        "total_tokens": 230,
    }
    assert summary["by_agent"]["atlas"]["model_calls"] == 1
    assert summary["by_model"]["azure_foundry:DeepSeek-V3.2"]["input_tokens"] == 80
    assert summary["by_phase"]["combined"]["output_tokens"] == 30
