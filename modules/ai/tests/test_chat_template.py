"""Preserve Codex instruction messages and Qwen tool/thinking semantics."""

import json
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined


class ChatTemplateTests(unittest.TestCase):
    def render(self, messages, **kwargs):
        def fail(message):
            raise ValueError(message)

        environment = Environment(undefined=StrictUndefined)
        environment.filters["tojson"] = json.dumps
        template = environment.from_string(
            (Path(__file__).parents[1] / "templates/qwen3.5.jinja").read_text()
        )
        return template.render(
            messages=messages,
            tools=kwargs.pop("tools", []),
            add_generation_prompt=True,
            add_vision_id=False,
            raise_exception=fail,
            **kwargs,
        )

    def test_multiple_instructions_preserve_order_with_tools(self):
        messages = [
            {"role": "developer", "content": "INITIAL"},
            {"role": "system", "content": [{"type": "text", "text": "SECOND"}]},
            {"role": "user", "content": "QUESTION"},
            {"role": "developer", "content": "UPDATE"},
            {"role": "user", "content": "FOLLOWUP"},
        ]
        prompt = self.render(
            messages,
            enable_thinking=False,
            tools=[{"type": "function", "function": {"name": "exec_command"}}],
        )
        self.assertIn("<tools>", prompt)
        self.assertIn("<function=example_function_name>", prompt)
        previous = -1
        for marker in ("INITIAL", "SECOND", "QUESTION", "UPDATE", "FOLLOWUP"):
            self.assertEqual(prompt.count(marker), 1)
            position = prompt.index(marker)
            self.assertGreater(position, previous)
            previous = position
        self.assertIn("<|im_start|>system\nUPDATE<|im_end|>", prompt)
        self.assertTrue(prompt.endswith("<think>\n\n</think>\n\n"))

    def test_thinking_enabled_and_plain_chat(self):
        prompt = self.render(
            [{"role": "user", "content": "QUESTION"}], enable_thinking=True
        )
        self.assertTrue(prompt.endswith("<|im_start|>assistant\n<think>\n"))
        self.assertNotIn("<tools>", prompt)

    def test_tool_call_and_result_keep_qwen_format(self):
        prompt = self.render(
            [
                {"role": "user", "content": "RUN"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "exec_command",
                                "arguments": {"cmd": "pwd"},
                            }
                        }
                    ],
                },
                {"role": "tool", "content": "/synthetic"},
                {"role": "developer", "content": "UPDATE"},
            ],
            enable_thinking=False,
        )
        self.assertIn("<tool_call>\n<function=exec_command>", prompt)
        self.assertIn("<parameter=cmd>\npwd\n</parameter>", prompt)
        self.assertIn("<tool_response>\n/synthetic\n</tool_response>", prompt)
        self.assertGreater(prompt.index("UPDATE"), prompt.index("/synthetic"))

    def test_system_images_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "cannot contain images"):
            self.render(
                [
                    {"role": "user", "content": "QUESTION"},
                    {"role": "developer", "content": [{"type": "image"}]},
                ],
                enable_thinking=False,
            )


if __name__ == "__main__":
    unittest.main()
