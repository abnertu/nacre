# Local AI benchmarks

Measured on 2026-10-06 with synthetic prompts and verified GGUFs. These results set the Arch host defaults; they are not a general performance claim.

## Setup

| Item | Spec |
| --- | --- |
| GPU | AMD RX 9060 XT (gfx1200), 16,304 MiB VRAM, counters from `/sys/class/drm/card1/device` |
| CPU / RAM | Ryzen 7 7700 (8C/16T), ~32 GB |
| Software | Kernel `7.2.6-arch2-1`, Mesa/Vulkan Radeon `26.2.3-1`, ROCm `7.2.4-1` |
| llama.cpp | build 10884, commit `434ddbbc0e30522e897670681e503b797c12b7c1` |
| Router | llama-swap 224 with the Nix-generated config |

`llama-bench` measured PP512, PP4096 and TG128, compared ROCm0 / Vulkan0, q8 / q4 KV, ubatch 64–1024, batch 1024 / 2048 and threads 4 / 8. Chosen settings: Vulkan0, all layers on GPU, flash attention on, q8 KV, batch 2048, ubatch 512, 8 threads. Raising ubatch to 1024 dropped 4B PP4096 from 3,277 to 2,979 tok/s and added ~508 MiB peak VRAM.

## Candidates

| Model | PP512 tok/s | PP4096 tok/s | TG128 tok/s | Peak GPU MiB |
| --- | ---: | ---: | ---: | ---: |
| Previous Qwen3.6 35B A3B MXFP4, ROCm, 16 GPU layers | 486 | — | 20.8 | 9,940 |
| Qwen3.5 9B Q4_K_M, Vulkan | 1,923 | 2,054 | 49.3 | ~6,667 |
| Qwen3.5 4B Q4_K_M, Vulkan | 2,568 | 3,274 | 80.3 | 4,401 |
| Qwen2.5 Coder 1.5B Q8_0, Vulkan | 6,069 | 9,039 | 145.8 | 3,090 |
| Qwen2.5 Coder 3B Q4_K_M, Vulkan | 3,295 | 4,804 | 118.4 | 3,382 |

Peaks include the desktop's own usage. Model identities and checksums are pinned in the [artifact inventory](../modules/ai/artifacts.nix).

- **4B is the default agent**: 9B missed the 50 tok/s target.
- **3B handles completion**: it passed all four small Python, JavaScript and Nix tests; 1.5B passed three. The set is too small to rank general coding ability.
- FIM prefixes need a language hint: without `# Nix expression`, both models misread a Nix snippet.

## Routing and context

Both models resident:

| Scenario | Agent generation | Completion generation | First content (warm) | Peak GPU |
| --- | --- | --- | --- | --- |
| 9,518-token prompt | 74.8 tok/s alone; 67.1–67.3 concurrent | 61.0–62.2 tok/s | agent 48–50 ms, completion 10–35 ms | 6,536 MiB |
| Near the old 32K limit, concurrent | 48.0–48.2 tok/s | — | cold 13.9 s | — |
| Final 16K, 15,168-token prompt, 128 tokens out | 72.4 alone; 50.2–59.9 concurrent | 60.8–84.3 tok/s | agent 50–55 ms (cold 6.71 s) | 6,263 MiB |

Speed dropped sharply near 32K, so the agent context defaults to 16K and completion to 4K. Larger contexts remain configurable at a measured cost. The final settings stayed above 50 tok/s in these samples, with little margin at long context.

Declared estimates are 6,144 MiB (agent) and 3,072 MiB (completion), within the 11,264 MiB budget. Sunshine streaming was not measured; memory headroom does not prove frame stability.

## Thinking and diagnosis

- The previous Qwen3.6 with `enable_thinking=false` answered `17 * 23` directly; with `true` it ran out of a 256-token limit before answering. Both decoded at ~21 tok/s, so disabling thinking did not fix slow decoding.
- The chosen 4B answered directly through the plain alias and correctly after reasoning through the thinking alias. Repeated requests reused the prompt cache; a synthetic tool call produced the expected `lookup_symbol` call.
- The previous model only partly fit in VRAM. The gains came from fully offloaded smaller models, Vulkan on this card, flash attention and a shorter context. One slot per backend lets both models work at once.
- The original GGUF has no MTP tensors, and the target was met without MTP.

References: [Unsloth Qwen3.6](https://unsloth.ai/docs/models/qwen3.6), [Qwen3.5 4B](https://huggingface.co/Qwen/Qwen3.5-4B), [Qwen2.5 Coder 1.5B](https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B), [llama.cpp HIP prompt processing](https://github.com/ggml-org/llama.cpp/issues/18823), [MTP buffers](https://github.com/ggml-org/llama.cpp/issues/26038).
