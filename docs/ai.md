# Local AI

Nacre serves declared GGUF models through pinned native llama.cpp and llama-swap. Nix generates routing, Caddy and systemd policy; the Arch adapter validates prepared artifacts, ownership and service readiness before convergence. Binaries and models remain at declared native paths outside the store.

```text
Tailnet HTTPS → Tailscale Serve → loopback Caddy → loopback llama-swap → loopback llama-server
```

Caddy exposes only `/health` and `/v1/*` through the tailnet route. The AI module declares model identities, profiles, runtime versions and checksums.

## Selecting models

`programs.ai.llama.model.name` selects the default. An empty `llama.models` uses single-model mode; an explicit selection must enable every referenced model, including the default:

```nix
programs.ai.llama = {
  model.name = "qwen3.5-4b-q4-k-m";
  concurrentModels = true;
  maxLoadedModels = 2;
  memoryBudgetMiB = 11264;
  models = {
    "qwen3.5-4b-q4-k-m" = {
      enable = true;
      contextSize = 16384;
      fit = false;
      gpuLayers = 99;
      vramEstimateMiB = 6144;
    };
    "qwen2.5-coder-3b-q4-k-m" = {
      enable = true;
      contextSize = 4096;
      vramEstimateMiB = 3072;
    };
  };
};
```

- Each model controls device, context, cache, batch, slots and offload. Per-model settings override `llama.model` settings for the default model.
- Profiles share a backend process and change sampling and thinking only.
- Evaluation rejects unknown fields, unselected profile targets, invalid batches and conflicting thinking options.
- Concurrent selection cannot exceed `maxLoadedModels`; backends load on demand and stay resident. Without concurrency, the limit is 1 and models swap on demand.
- Preparation covers the selection; deselection removes no artifacts.

`memoryBudgetMiB` requires a `vramEstimateMiB` for every selected model and rejects a sum above the budget. These are planning estimates, not allocation limits. Fixed offload, context and batch with `fit = false` avoid load-order-dependent fitting. Measure peak prompt processing with desktop and Sunshine headroom, and remeasure after runtime or model changes.

The option name `qwen3.6-35b-a3b-ud-q5-k-m` is kept for compatibility; the file is MXFP4_MOE. Query `/v1/models` for exact API IDs.

## Agent tools

With `programs.ai.enable`, the AI module installs these AUR packages, each with its own switch:

| Package | Option |
| --- | --- |
| Claude Code (`claude-code`) | `programs.ai.claude.enable` |
| Claude Desktop (`claude-desktop`, only with the desktop) | `programs.ai.claudeDesktop.enable` |
| Codex (`openai-codex-bin`) | `programs.ai.codex.enable` |

Install newly declared native tools with `nacre update`; a routine switch exits 3 while they are missing.

## Agent skills

Home Manager projects selected skill directories from pinned upstream sources:

- `~/.agents/skills` follows `programs.ai.enable` and `programs.ai.skillsPresets.enable`;
- `~/.claude/skills` follows `programs.ai.claude.enable` and `programs.ai.claude.skills.enable`;
- none depends on llama.cpp preparation.

Choose one installation source per skill to avoid duplicate discovery through managed links and plugins.

[`modules/ai/skills.nix`](../modules/ai/skills.nix) owns the selection from the locked `matt-pocock-skills`, `obsidian-skills` and `vercel-skills` inputs. Activation uses prebuilt sources without downloads or a Skills CLI lockfile.

Update skill sources after reviewing upstream changes:

```bash
nix flake update matt-pocock-skills obsidian-skills vercel-skills
just check
just build
```

Review and commit the lock update before deployment; revert it to restore earlier sources. `nacre update` does not advance skill inputs. Missing selected paths or `SKILL.md` files fail evaluation. Managed skill links are read-only; update their flake inputs rather than running a skill updater against them.

## Codex local profile

When AI, Codex and llama.cpp are enabled, Home Manager generates `~/.codex/llama-cpp.config.toml` using the default model identity and context:

- provider `llama_cpp` (Responses API at `http://127.0.0.1:11434/v1`), web search off;
- auto-compaction at 75% of context (12K tokens at the default 16K);
- Codex multi-agent tools off, because the pinned llama.cpp Responses bridge supports only function tools.

Select the generated profile with `codex --profile llama-cpp` from the default Codex home. The managed profile is not projected into a custom `CODEX_HOME`. Disable it with `programs.ai.codex.localProfile.enable = false`; other Codex preferences and credentials remain unmanaged.

The managed Qwen3.5 template preserves multiple system/developer messages in order. The bundled GGUF template rejects that input with HTTP 500 (`System message must be at the beginning`); a client may present a generic overload message.

## FIM completion

Send raw prefix/suffix tokens to `/v1/completions` for fill-in-the-middle completion:

```bash
curl --fail http://127.0.0.1:11434/v1/completions \
  -H 'Content-Type: application/json' \
  --data '{"model":"Qwen2.5-Coder-3B-Q4_K_M.gguf","prompt":"<|fim_prefix|>def add(a, b):\n    <|fim_suffix|>\n\nassert add(2, 3) == 5\n<|fim_middle|>","max_tokens":64,"temperature":0,"stop":["<|fim_pad|>","<|endoftext|>","<|im_end|>"]}'
```

Specify stop tokens for the selected model. Add a language or filename hint such as `# Nix expression` when the prefix is ambiguous.

## Benchmarks

Benchmark tools use the real GPU outside deployment and CI. Stage candidates in scratch space and verify SHA-256. Isolated measurements may require stopping the router and restoring it afterwards; retain managed configuration, receipts and the prepared selector.

Find the discrete GPU's sysfs path instead of assuming `card0`:

```bash
for device in /sys/class/drm/card[0-9]/device; do
  test ! -f "$device/mem_info_vram_total" || {
    printf '%s\n' "$device"
    cat "$device/mem_info_vram_total" "$device/mem_info_vram_used"
  }
done
python modules/ai/benchmark.py \
  --model /path/to/verified-model.gguf \
  --binary-prefix /opt/llama-cpp-opencode/current \
  --device-path /sys/class/drm/card1/device \
  --devices ROCm0,Vulkan0 --batches 2048 --ubatches 64,512 \
  --caches q8_0,q4_0 --threads 8 --gpu-layers 99 \
  --min-free-mib 4096 --output /var/tmp/ai-bench.json
```

The benchmark repeats PP512, PP4096 and TG128 and records runtime version, model checksum, parameters, diagnostics and peak VRAM. `--depths 8192` adds generation after a longer prefix. The headroom monitor stops benchmark-owned processes, but polling can miss brief allocations.

```bash
python modules/ai/probe.py --base-url http://127.0.0.1:11434 \
  --model MODEL_ID --thinking-model MODEL_ID:thinking-coding \
  --output /var/tmp/ai-chat.json
python modules/ai/probe.py --base-url http://127.0.0.1:11434 \
  --model COMPLETION_ID --mode fim --output /var/tmp/ai-fim.json
```

The probe compares thinking modes and repeated synthetic prefixes, recording first SSE event, reasoning, visible answer, failures and partial output separately. Empty-context TG128 does not predict long-context generation. See [measured results](ai-benchmarks.md) for the recorded workstation experiment.

## Preparation

```bash
nacre ai prepare          # build and verify every declared artifact
nacre ai prepare build    # only the pinned llama.cpp
nacre ai prepare model    # only download and fully verify the declared models
```

- Build the declared runtime and patches with native C++, ROCm and Vulkan tools, install into a versioned directory and atomically select it through `current`.
- Stage models by identity, fully verify SHA-256 before atomic publication and record a root-owned receipt. Routine deployment compares that identity and metadata without rehashing the GGUF.
- Unknown staging state, selector mismatch and checksum mismatch require manual resolution.
- Downloads use `hf download --local-dir`. Retry `nacre ai prepare model` to resume matching staged downloads and verify them before publication.

## Deploying and checking

```bash
nacre switch
curl --fail http://127.0.0.1:11434/v1/models
curl --fail http://127.0.0.1:11435/v1/models
sudo tailscale serve status --json
systemctl status llama-swap.service caddy.service
```

Before a build selector exists, deployment reports AI as unprepared and leaves it untouched. After preparation, missing models, invalid receipts, checksum drift, unmanaged Caddy state, service failures and post-preflight changes stop convergence.

Disabling AI withdraws management. Purge removes its Tailscale Serve route, Caddy site and llama-swap resources while retaining prepared binaries, models and receipts.
