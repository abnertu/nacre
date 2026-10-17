#!/usr/bin/env python3
"""Measure synthetic chat/FIM requests against an explicitly selected local server."""

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, cast


def request(base_url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    first_event: float | None = None
    first_reasoning: float | None = None
    first_content: float | None = None
    content = reasoning = ""
    timings: dict[str, Any] = {}
    usage: dict[str, Any] = {}
    endpoint = "/v1/chat/completions" if "messages" in payload else "/v1/completions"
    req = urllib.request.Request(
        base_url + endpoint,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    completed = False
    failure: str | None = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            for raw in response:
                if time.monotonic() - started > timeout:
                    raise TimeoutError("total request deadline exceeded")
                if not raw.startswith(b"data: "):
                    continue
                data = raw[6:].strip()
                if data == b"[DONE]":
                    completed = True
                    break
                event = cast("dict[str, Any]", json.loads(data))
                elapsed = time.monotonic() - started
                if first_event is None:
                    first_event = elapsed
                if "error" in event:
                    raise RuntimeError(str(event["error"]))
                timings.update(event.get("timings", {}))
                usage.update(event.get("usage", {}))
                for choice in event.get("choices", []):
                    if choice.get("finish_reason") is not None:
                        completed = True
                    delta = choice.get("delta", {})
                    text = delta.get("content") or choice.get("text") or ""
                    thought = (
                        delta.get("reasoning_content") or delta.get("reasoning") or ""
                    )
                    if text and first_content is None:
                        first_content = elapsed
                    if thought and first_reasoning is None:
                        first_reasoning = elapsed
                    content += text
                    reasoning += thought
        if not completed:
            failure = "stream ended without a completion marker"
    except urllib.error.HTTPError as error:
        with error:
            failure = f"HTTP {error.code}: {error.read(8192).decode(errors='replace')}"
    except (OSError, ValueError, RuntimeError) as error:
        failure = str(error)
    return {
        "elapsed_seconds": time.monotonic() - started,
        "first_event_seconds": first_event,
        "first_reasoning_seconds": first_reasoning,
        "first_content_seconds": first_content,
        "content": content,
        "reasoning": reasoning,
        "timings": timings,
        "usage": usage,
    } | ({"error": failure} if failure else {})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--thinking-model", help="router alias for thinking-on requests"
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", choices=["chat", "fim"], default="chat")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--max-tokens", type=int, default=256)
    args = parser.parse_args()
    url = urllib.parse.urlsplit(str(args.base_url))
    if (
        url.scheme != "http"
        or url.hostname not in ("127.0.0.1", "localhost", "::1")
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in ("", "/")
    ):
        parser.error("base-url must be an HTTP loopback origin without credentials")
    if args.timeout <= 0 or args.max_tokens <= 0:
        parser.error("timeout and max-tokens must be positive")
    rows: list[dict[str, Any]] = []
    for thinking in [False, True] if args.mode == "chat" else [None]:
        for repeat in range(2):
            payload: dict[str, Any] = {
                "model": args.thinking_model
                if thinking is True and args.thinking_model
                else args.model,
                "stream": True,
                "max_tokens": args.max_tokens,
                "temperature": 0.6,
                "seed": 42,
                "stream_options": {"include_usage": True},
                "timings_per_token": True,
            }
            if thinking is None:
                payload["temperature"] = 0.0
                payload["prompt"] = (
                    "<|fim_prefix|>def add(a, b):\n    <|fim_suffix|>\n\nassert add(2, 3) == 5\n<|fim_middle|>"
                )
                payload["stop"] = ["<|fim_pad|>", "<|endoftext|>", "<|im_end|>"]
            else:
                payload["messages"] = [
                    {
                        "role": "user",
                        "content": "Calculate 17 * 23. Give the answer in one sentence.",
                    }
                ]
                payload["chat_template_kwargs"] = {"enable_thinking": thinking}
            row: dict[str, Any] = {
                "thinking": thinking,
                "repeat": repeat,
                "request": payload,
            }
            try:
                row.update(request(args.base_url.rstrip("/"), payload, args.timeout))
            except (OSError, ValueError, RuntimeError) as error:
                row["error"] = str(error)
            rows.append(row)
            args.output.write_text(
                json.dumps(
                    {"base_url": args.base_url, "model": args.model, "rows": rows},
                    indent=2,
                )
                + "\n"
            )
    return int(any("error" in row for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
