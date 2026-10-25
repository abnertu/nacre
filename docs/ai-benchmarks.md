# Local AI benchmark record

Measurements from 2026-10-06 used synthetic prompts and checksum-verified GGUFs on the workstation below. They selected a workstation profile at that time. They do not describe the current inventory defaults. Requalify settings for the current hardware and workload.

## Measurement environment

| Item | Spec |
| --- | --- |
| GPU | AMD RX 9060 XT (gfx1200), 16,304 MiB VRAM, counters from `/sys/class/drm/card1/device` |
| CPU / RAM | Ryzen 7 7700 (8C/16T), ~32 GB |
| Software | Kernel `7.2.6-arch2-1`, Mesa/Vulkan Radeon `26.2.3-1`, ROCm `7.2.4-1` |
| llama.cpp | build 10884, commit `434ddbbc0e30522e897670681e503b797c12b7c1` |
| Router | llama-swap 224 with the Nix-generated config |

`llama-bench` measured PP512, PP4096 and TG128. It compared these values:

- ROCm0 / Vulkan0.
- q8 / q4 KV.
- ubatch 64–1024 and batch 1024 / 2048.
- Threads 4 / 8.

The selected run used these settings:

- Device: Vulkan0.
- Layers: all on GPU.
- Flash attention: on.
- KV: q8.
- Batch: 2048.
- Ubatch: 512.
- Threads: 8.

With ubatch 1024, 4B PP4096 dropped from 3,277 to 2,979 tok/s. Peak VRAM increased by ~508 MiB.

## Candidate measurements

| Model | PP512 tok/s | PP4096 tok/s | TG128 tok/s | Peak GPU MiB |
| --- | ---: | ---: | ---: | ---: |
| Previous Qwen3.6 35B A3B MXFP4, ROCm, 16 GPU layers | 486 | — | 20.8 | 9,940 |
| Qwen3.5 9B Q4_K_M, Vulkan | 1,923 | 2,054 | 49.3 | ~6,667 |
| Qwen3.5 4B Q4_K_M, Vulkan | 2,568 | 3,274 | 80.3 | 4,401 |
| Qwen2.5 Coder 1.5B Q8_0, Vulkan | 6,069 | 9,039 | 145.8 | 3,090 |
| Qwen2.5 Coder 3B Q4_K_M, Vulkan | 3,295 | 4,804 | 118.4 | 3,382 |

Peaks include the usage of the desktop. The [artifact inventory](../modules/ai/artifacts.nix) pins model identities and checksums.

- **That experiment selected 4B as the agent**: 9B missed the 50 tok/s target.
- **That experiment selected 3B for completion**: it passed all four small Python, JavaScript and Nix tests. 1.5B passed three. The set is too small to rank general coding ability.
- FIM prefixes need a language hint. Without `# Nix expression`, both models misread a Nix snippet.

## Concurrent routing and context

The following runs kept both selected models resident:

| Scenario | Agent generation | Completion generation | First content (warm) | Peak GPU |
| --- | --- | --- | --- | --- |
| 9,518-token prompt | 74.8 tok/s alone; 67.1–67.3 concurrent | 61.0–62.2 tok/s | agent 48–50 ms, completion 10–35 ms | 6,536 MiB |
| Near the old 32K limit, concurrent | 48.0–48.2 tok/s | — | cold 13.9 s | — |
| Final 16K, 15,168-token prompt, 128 tokens out | 72.4 alone; 50.2–59.9 concurrent | 60.8–84.3 tok/s | agent 50–55 ms (cold 6.71 s) | 6,263 MiB |

Speed dropped sharply near 32K. That experiment used 16K agent context and 4K completion context. Larger contexts stay configurable, at a measured cost. These final samples exceeded 50 tok/s, with little margin at long context.

That configuration declared 6,144 MiB (agent) and 3,072 MiB (completion), within its 11,264 MiB budget. Sunshine streaming was not measured. Thus these results make no claim about frame stability.

## Observations

- The previous Qwen3.6 with `enable_thinking=false` answered `17 * 23` directly. With `true`, it used all of a 256-token limit before it answered. Both decoded at ~21 tok/s. Thus thinking off did not fix slow decoding.
- The chosen 4B answered directly through the plain alias. Through the thinking alias, it answered correctly after reasoning. Repeated requests used the prompt cache again. A synthetic tool call produced the expected `lookup_symbol` call.
- The previous model only partly fit in VRAM. The gains came from fully offloaded smaller models, Vulkan on this card, flash attention and a shorter context. One slot per backend lets both models work at once.
- The original GGUF has no MTP tensors, and the target was met without MTP.

References: [Unsloth Qwen3.6](https://unsloth.ai/docs/models/qwen3.6), [Qwen3.5 4B](https://huggingface.co/Qwen/Qwen3.5-4B), [Qwen2.5 Coder 1.5B](https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B), [llama.cpp HIP prompt processing](https://github.com/ggml-org/llama.cpp/issues/18823), [MTP buffers](https://github.com/ggml-org/llama.cpp/issues/26038).
