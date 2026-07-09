import logging
import time

import anthropic

from config import settings

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def call_claude_tool(
    system_prompt: str,
    user_prompt: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict,
    max_tokens: int = 2048,
    max_retries: int = 2,
) -> dict:
    """Force Claude to respond via a single structured tool call and return its `input` dict.

    Using tool-use instead of free-text parsing means we get reliable JSON back
    instead of having to regex/parse a text response.
    """
    client = _get_client()
    tool = {"name": tool_name, "description": tool_description, "input_schema": input_schema}

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=settings.claude_model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                tools=[tool],
                tool_choice={"type": "tool", "name": tool_name},
            )
            usage = response.usage
            logger.info(
                "claude call ok tool=%s input_tokens=%d output_tokens=%d stop_reason=%s",
                tool_name,
                usage.input_tokens,
                usage.output_tokens,
                response.stop_reason,
            )
            if response.stop_reason == "max_tokens":
                logger.warning(
                    "claude response for tool=%s was truncated at max_tokens=%d — "
                    "results may be incomplete/malformed; consider raising max_tokens",
                    tool_name,
                    max_tokens,
                )
            for block in response.content:
                if block.type == "tool_use" and block.name == tool_name:
                    return block.input
            raise RuntimeError(f"Claude response did not include a {tool_name} tool call")
        except anthropic.APIStatusError as exc:
            last_error = exc
            retryable = exc.status_code >= 500 or exc.status_code == 429
            if not retryable or attempt == max_retries - 1:
                raise
            wait_seconds = 2**attempt
            logger.warning("Claude API error %s, retrying in %ds", exc, wait_seconds)
            time.sleep(wait_seconds)

    assert last_error is not None
    raise last_error
