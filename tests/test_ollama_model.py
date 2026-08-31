# SPDX-License-Identifier: MPL-2.0

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from ulg.actions import ListFilesAction
from ulg.config import load_config
from ulg.model import ChatMessage, ModelProtocolError, OllamaModel


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


class _Chunk:
    def __init__(self, content: str) -> None:
        self.message = _Message(content)


class _StubClient:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks
        self.arguments: dict[str, object] = {}
        self.closed = False

    def chat(self, **kwargs: object) -> Iterator[_Chunk]:
        self.arguments = kwargs
        return iter(_Chunk(chunk) for chunk in self._chunks)

    def close(self) -> None:
        self.closed = True


class _TimeoutClient(_StubClient):
    def chat(self, **kwargs: object) -> Iterator[_Chunk]:
        del kwargs

        def fail() -> Iterator[_Chunk]:
            raise httpx.ReadTimeout("timed out")
            yield _Chunk("")

        return fail()


def test_ollama_model_streams_and_strictly_validates_action() -> None:
    task_id = uuid4()
    action = ListFilesAction(task_id=task_id, rationale="inspect", path=".")
    payload = action.model_dump_json()
    client = _StubClient([payload[:20], payload[20:]])
    settings = load_config(Path("config/policy.example.toml")).model
    model = OllamaModel(settings, client=client)

    result = model.propose(
        task_id=task_id,
        messages=[ChatMessage(role="user", content="inspect the project")],
    )

    assert result == action
    assert client.arguments["stream"] is True
    assert client.arguments["format"] == "json"
    assert client.arguments["options"] == {"temperature": 0}
    messages = client.arguments["messages"]
    assert isinstance(messages, list)
    assert "apply_patch: patch" in messages[0]["content"]
    assert "when type is apply_patch" in messages[0]["content"]
    assert "Unified diff rules" in messages[0]["content"]


def test_ollama_model_advertises_run_task_only_when_enabled() -> None:
    task_id = uuid4()
    action = ListFilesAction(task_id=task_id, rationale="inspect", path=".")
    client = _StubClient([action.model_dump_json()])
    settings = load_config(Path("config/policy.example.toml")).model
    model = OllamaModel(
        settings,
        client=client,
        enable_run_task=True,
        allowed_recipes=("test", "lint"),
    )

    model.propose(task_id=task_id, messages=[])

    messages = client.arguments["messages"]
    assert isinstance(messages, list)
    assert "run_task: recipe_name" in messages[0]["content"]
    assert '"run_task"' in messages[0]["content"]
    assert '"test"' in messages[0]["content"]
    assert '"lint"' in messages[0]["content"]


def test_ollama_model_rejects_wrong_task_and_oversized_response() -> None:
    task_id = uuid4()
    wrong_action = ListFilesAction(task_id=uuid4(), rationale="inspect", path=".")
    settings = load_config(Path("config/policy.example.toml")).model
    model = OllamaModel(settings, client=_StubClient([wrong_action.model_dump_json()]))

    with pytest.raises(ModelProtocolError, match="task_id"):
        model.propose(
            task_id=task_id,
            messages=[ChatMessage(role="user", content="inspect")],
        )

    tiny_settings = settings.model_copy(update={"max_response_bytes": 2})
    tiny_model = OllamaModel(tiny_settings, client=_StubClient(["{}"] * 2))
    with pytest.raises(ModelProtocolError, match="byte limit"):
        tiny_model.propose(
            task_id=task_id,
            messages=[ChatMessage(role="user", content="inspect")],
        )


def test_ollama_model_normalizes_transport_timeout() -> None:
    task_id = uuid4()
    settings = load_config(Path("config/policy.example.toml")).model
    model = OllamaModel(settings, client=_TimeoutClient([]))

    with pytest.raises(ModelProtocolError, match="timed out"):
        model.propose(
            task_id=task_id,
            messages=[ChatMessage(role="user", content="inspect")],
        )


def test_ollama_model_enforces_total_stream_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    settings = load_config(Path("config/policy.example.toml")).model.model_copy(
        update={"request_timeout_seconds": 1}
    )
    action = ListFilesAction(task_id=task_id, rationale="inspect", path=".")
    model = OllamaModel(settings, client=_StubClient([action.model_dump_json()]))
    clock = iter((0.0, 2.0))
    monkeypatch.setattr("ulg.model.ollama.time.monotonic", lambda: next(clock))

    with pytest.raises(ModelProtocolError, match="timed out"):
        model.propose(
            task_id=task_id,
            messages=[ChatMessage(role="user", content="inspect")],
        )
