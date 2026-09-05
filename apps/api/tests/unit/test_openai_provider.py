"""The OpenAI provider's pure parts: redaction, argument decoding, translation.

No network, no key, no SDK call. What is covered here is everything that can be
wrong without a request ever being made — and message translation is exactly the
kind of code that looks obviously right and silently drops a field.

The one thing these cannot cover is a real round trip. That is deliberate: a
test that calls the API asserts what OpenAI did, costs money, and fails when the
network does. The loop's behaviour is covered against the deterministic provider
in ``tests/integration/test_agent.py``.
"""

from __future__ import annotations

import json

import pytest

from app.agent.provider import Message, ProviderError, ToolCall
from app.agent.providers.openai_provider import (
    DEFAULT_MODEL,
    OpenAIProvider,
    _parse_arguments,
    _to_openai,
    redact,
)

#: Obviously fake, and shaped like a key so the redaction path is exercised.
FAKE_KEY = "sk-notarealkey0000000000000000"


class TestRedaction:
    """SDK errors sometimes echo request headers. This is the last line."""

    def test_a_key_shaped_string_is_removed(self) -> None:
        assert FAKE_KEY not in redact(f"Incorrect API key provided: {FAKE_KEY}")

    def test_the_surrounding_message_survives(self) -> None:
        """Scrubbing must not destroy the diagnostic — only the credential."""
        redacted = redact(f"Incorrect API key provided: {FAKE_KEY}. Check your account.")
        assert redacted.startswith("Incorrect API key provided: sk-***")
        assert "Check your account." in redacted

    def test_every_occurrence_goes(self) -> None:
        assert redact(f"{FAKE_KEY} and again {FAKE_KEY}").count("sk-***") == 2

    def test_text_with_no_key_is_untouched(self) -> None:
        message = "Connection timed out after 60 seconds."
        assert redact(message) == message


class TestConstruction:
    def test_an_empty_key_is_refused_rather_than_sent(self) -> None:
        """Reaching the constructor without a key means a check was skipped."""
        with pytest.raises(ProviderError) as caught:
            OpenAIProvider(api_key="")
        assert "OPENAI_API_KEY" in str(caught.value)
        assert "never be exposed to the browser" in str(caught.value)

    def test_an_unset_model_falls_back_to_a_named_default(self) -> None:
        provider = OpenAIProvider(api_key=FAKE_KEY, model="")
        assert provider.model == DEFAULT_MODEL

    def test_an_explicit_model_is_honoured(self) -> None:
        assert OpenAIProvider(api_key=FAKE_KEY, model="gpt-4.1").model == "gpt-4.1"

    def test_the_key_is_not_stored_on_a_public_attribute(self) -> None:
        """Nothing an API response could reach by iterating the object."""
        provider = OpenAIProvider(api_key=FAKE_KEY)
        public = {
            name: getattr(provider, name)
            for name in dir(provider)
            if not name.startswith("_") and not callable(getattr(provider, name))
        }
        assert FAKE_KEY not in json.dumps(public, default=str)


class TestArgumentDecoding:
    """A model can emit anything. None of it may raise out of the loop."""

    def test_a_normal_object_decodes(self) -> None:
        assert _parse_arguments('{"mmsi": "366000001"}') == {"mmsi": "366000001"}

    @pytest.mark.parametrize("raw", [None, "", "{not json", "[1, 2, 3]", '"a string"', "42"])
    def test_anything_unusable_becomes_an_empty_object(self, raw: str | None) -> None:
        """Not a silent failure: the tool's own model then rejects it.

        Empty arguments reach `tools.execute`, fail validation, and the model is
        told what was wrong — a better outcome than raising and losing the run.
        """
        assert _parse_arguments(raw) == {}


class TestMessageTranslation:
    def test_a_system_turn_keeps_its_role(self) -> None:
        assert _to_openai(Message(role="system", content="rules")) == {
            "role": "system",
            "content": "rules",
        }

    def test_a_user_turn_carries_the_question_as_content(self) -> None:
        """The question is data in a user turn, never appended to the system prompt."""
        assert _to_openai(Message(role="user", content="How many vessels?")) == {
            "role": "user",
            "content": "How many vessels?",
        }

    def test_a_tool_result_is_linked_back_to_its_request(self) -> None:
        """Without `tool_call_id` the API cannot pair a result to its call."""
        payload = _to_openai(Message(role="tool", content='{"count": 3}', tool_call_id="call-7"))
        assert payload == {
            "role": "tool",
            "tool_call_id": "call-7",
            "content": '{"count": 3}',
        }

    def test_an_assistant_tool_request_is_re_encoded_in_full(self) -> None:
        payload = _to_openai(
            Message(
                role="assistant",
                content="",
                tool_calls=(
                    ToolCall(id="c1", name="get_vessel_details", arguments={"mmsi": "366000001"}),
                ),
            )
        )
        assert payload["role"] == "assistant"
        # Empty content becomes null: the API rejects an assistant turn that has
        # both an empty string and tool calls.
        assert payload["content"] is None
        call = payload["tool_calls"][0]
        assert call["id"] == "c1"
        assert call["type"] == "function"
        assert call["function"]["name"] == "get_vessel_details"
        assert json.loads(call["function"]["arguments"]) == {"mmsi": "366000001"}

    def test_a_multi_call_assistant_turn_keeps_every_call_and_its_order(self) -> None:
        payload = _to_openai(
            Message(
                role="assistant",
                tool_calls=(
                    ToolCall(id="c1", name="get_dataset_overview", arguments={}),
                    ToolCall(id="c2", name="get_speed_distribution", arguments={}),
                ),
            )
        )
        assert [call["id"] for call in payload["tool_calls"]] == ["c1", "c2"]

    def test_an_assistant_turn_with_prose_and_calls_keeps_both(self) -> None:
        payload = _to_openai(
            Message(
                role="assistant",
                content="Checking the archive first.",
                tool_calls=(ToolCall(id="c1", name="get_dataset_overview", arguments={}),),
            )
        )
        assert payload["content"] == "Checking the archive first."
        assert len(payload["tool_calls"]) == 1

    def test_a_round_trip_survives_json_encoding(self) -> None:
        """Whatever comes out must actually be sendable."""
        messages = [
            Message(role="system", content="rules"),
            Message(role="user", content="How many vessels?"),
            Message(
                role="assistant",
                tool_calls=(ToolCall(id="c1", name="get_dataset_overview", arguments={}),),
            ),
            Message(role="tool", content='{"distinctVessels": 16294}', tool_call_id="c1"),
        ]
        encoded = json.dumps([_to_openai(message) for message in messages])
        assert json.loads(encoded)[3]["tool_call_id"] == "c1"
