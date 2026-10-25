# Local AI

Nacre serves declared GGUF models through pinned native llama.cpp and llama-swap. Nix generates routing, Caddy and systemd policy. Before convergence, the Arch adapter validates prepared artifacts, ownership and service readiness. Binaries and models stay at declared native paths outside the store.

```text
Tailnet HTTPS → Tailscale Serve → loopback Caddy → loopback llama-swap → loopback llama-server
```

Caddy exposes only `/health` and `/v1/*` through the tailnet route. The AI module declares model identities, profiles, runtime versions and checksums.

## Selecting models

`programs.ai.llama.model.name` selects the default. An empty `llama.models` uses single-model mode. An explicit selection must enable each referenced model, also the default:

```nix
programs.ai.llama = {
  model = {
    name = "qwen3.5-4b-q4-k-m";
    device = "Vulkan0";
  };
  concurrentModels = true;
  maxLoadedModels = 2;
  memoryBudgetMiB = 10240;
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

- Declare the device for your machine. Each model controls device, context, cache, batch, slots and offload. Per-model settings override `llama.model` settings for the default model.
- `threads` and `threadsBatch` set generation and prompt-processing CPU threads. Unset values use the native defaults.
- Backends use Jinja templates, disable context shifting, and disable the host-memory prompt cache.
- Profiles share a backend process and change sampling and thinking only.
- The target model supplies each profile's defaults. Explicit profile fields override those defaults individually.
- `enableThinking` controls new reasoning. `preserveThinking` retains earlier reasoning where the model template supports it.
- These controls are independent. The managed Qwen3.5 template does not support earlier-turn preservation.
- Evaluation rejects unknown fields, unselected profile targets, invalid batches and unsupported reasoning preservation.
- Concurrent selection cannot exceed `maxLoadedModels`. Backends load on demand and stay resident. Without concurrency, the limit is 1, and models swap on demand.
- Preparation covers the selection. Deselection removes no artifacts.

`memoryBudgetMiB` needs a `vramEstimateMiB` for each selected model.
Concurrent models use the sum of their estimates.
Exclusive models use the largest estimate because they swap on demand.
These are planning estimates, not allocation limits.
Fixed offload, context and batch with `fit = false` prevent fitting that depends on load order.
Measure peak prompt processing with headroom for the desktop and Sunshine.
After runtime or model changes, measure again.

Set `vramLimitsMiB` to enforce kernel limits for the router and all its backends:

```nix
programs.ai.llama.vramLimitsMiB = {
  "drm/0000:03:00.0/vram" = 10239;
  "drm/0000:12:00.0/vram" = 1;
};
```

Use the region names reported by your driver.
This example divides a total 10 GiB budget between two GPU regions.
The startup guard enables `dmem` in the service's ancestors and verifies each `dmem.max` limit before starting inference.
A missing controller, missing region, existing allocation, or failed readback prevents startup.
An empty map disables this guard.
The limits cover all aliases and backend children together.
The desktop stays outside the service cgroup.
Drivers can move allocations to host memory when VRAM is exhausted.
Qualify fixed offload and context settings separately to avoid that slowdown.

Select the Unsloth MXFP4 artifact with `qwen3.6-35b-a3b-mxfp4-moe`.
Its runtime defaults use 32K context, 26 CPU expert layers, microbatch 128, and eight CPU threads.
The default alias uses the general-thinking recipe.
Measure these fixed settings on your hardware before deployment.
Query `/v1/models` for exact API IDs.

## Agent tools

With `programs.ai.enable`, the AI module installs these AUR packages, each with its own switch:

| Package | Option |
| --- | --- |
| Claude Code (`claude-code`) | `programs.ai.claude.enable` |
| Claude Desktop (`claude-desktop`, only with the desktop) | `programs.ai.claudeDesktop.enable` |
| Codex (`openai-codex-bin`) | `programs.ai.codex.enable` |

Install newly declared native tools with `nacre update`. A routine switch exits 3 while they are missing.

## Agent skills

Home Manager projects selected skill directories from pinned upstream sources:

- `~/.agents/skills` follows `programs.ai.enable` and `programs.ai.skillsPresets.enable`.
- `~/.claude/skills` follows `programs.ai.claude.enable` and `programs.ai.claude.skills.enable`.
- Neither depends on llama.cpp preparation.

Choose one installation source for each skill. Otherwise, managed links and plugins discover it twice.

[`modules/ai/skills.nix`](../modules/ai/skills.nix) owns the selection from the locked `matt-pocock-skills`, `obsidian-skills` and `vercel-skills` inputs. Activation uses prebuilt sources without downloads or a Skills CLI lockfile.

Review the upstream changes. Then update the skill sources:

```bash
nix flake update matt-pocock-skills obsidian-skills vercel-skills
just check
just build
```

Review and commit the lock update before deployment. To restore earlier sources, revert it. `nacre update` does not advance skill inputs. Missing selected paths or `SKILL.md` files fail evaluation. Managed skill links are read-only. Update their flake inputs. Do not run a skill updater against them.

## Codex local profile

When AI, Codex and llama.cpp are enabled, Home Manager generates `~/.codex/llama-cpp.config.toml`. It uses the default model identity and context:

- Provider `llama_cpp` (Responses API at `http://127.0.0.1:11434/v1`), with web search off.
- Auto-compaction at 75% of the selected context.
- Codex multi-agent tools off. The pinned llama.cpp Responses bridge supports only function tools.

From the default Codex home, select the generated profile with `codex --profile llama-cpp`. Home Manager does not project the managed profile into a custom `CODEX_HOME`. To disable it, set `programs.ai.codex.localProfile.enable = false`. Other Codex preferences and credentials stay unmanaged.

The managed Qwen3.5 template preserves multiple system/developer messages in order. The bundled GGUF template rejects that input with HTTP 500 (`System message must be at the beginning`). A client can show a generic overload message.

## FIM completion

For fill-in-the-middle completion, send raw prefix/suffix tokens to `/v1/completions`:

```bash
curl --fail http://127.0.0.1:11434/v1/completions \
  -H 'Content-Type: application/json' \
  --data '{"model":"Qwen2.5-Coder-3B-Q4_K_M.gguf","prompt":"<|fim_prefix|>def add(a, b):\n    <|fim_suffix|>\n\nassert add(2, 3) == 5\n<|fim_middle|>","max_tokens":64,"temperature":0,"stop":["<|fim_pad|>","<|endoftext|>","<|im_end|>"]}'
```

Specify stop tokens for the selected model. When the prefix is ambiguous, add a language or filename hint, such as `# Nix expression`.

## Benchmarks

Benchmark tools use the real GPU outside deployment and CI. Stage candidates in scratch space and verify SHA-256. For isolated measurements, you can stop the router. Restore it after the measurement. Keep the managed configuration, the receipts and the prepared selector.

Find the sysfs path of the discrete GPU. Do not assume `card0`:

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

The benchmark repeats PP512, PP4096 and TG128. It records runtime version, model checksum, parameters, diagnostics and sampled peak VRAM. `--depths 8192` adds generation after a longer prefix. `--cpu-moe-layers 24,28,32` compares CPU expert placement. An empty matrix fails.

Use `--prompt-tokens 128,512 --generation-tokens 32 --repetitions 1` for a short placement screen.
Confirm promising placements with longer prefixes and repetitions.

The headroom monitor stops benchmark-owned process groups. Polling can miss brief allocations. Aggregate GPU counters include desktop use.

For a kernel device-memory limit, supply an empty delegated cgroup:

```bash
python modules/ai/benchmark.py \
  --model /path/to/verified-model.gguf \
  --binary-prefix /opt/llama-cpp-opencode/current \
  --device-path /sys/class/drm/card1/device --devices Vulkan0 \
  --cpu-moe-layers 24,28 --ubatches 128 --caches q8_0 \
  --cgroup /sys/fs/cgroup/path/to/experiment \
  --dmem-region drm/0000:03:00.0/vram --max-vram-mib 10240 \
  --min-free-mib 0 --min-host-available-mib 4096 --reject-vram-spill \
  --output /var/tmp/ai-bench-limited.json
```

The command sets `dmem.max` before launching children and rejects populated groups. It disables group swap when that controller exists. It records available host memory and group memory counters. It records lifetime VRAM peaks when `dmem.peak` exists. Sampled group peaks are lower bounds. Counter failures stop the run. The command does not create or delegate cgroups.

Verify driver accounting and enforcement with disposable allocations before loading weights. Keep the desktop outside the experiment group. `--min-free-mib` controls aggregate free space; it does not set the model allocation limit. Benchmark children inherit only PATH, locale, runtime-directory and device-selector variables. Their library path uses the selected prefix.

The monitor deduplicates DRM clients across group processes and descriptors. It records requested VRAM, resident VRAM, and resident GTT separately. `--reject-vram-spill` stops a run when requested VRAM becomes nonresident. These sampled counters can miss short migrations.

```bash
python modules/ai/probe.py --base-url http://127.0.0.1:11434 \
  --model MODEL_ID --thinking-model MODEL_ID:thinking-coding \
  --output /var/tmp/ai-chat.json
python modules/ai/probe.py --base-url http://127.0.0.1:11434 \
  --model COMPLETION_ID --mode fim --output /var/tmp/ai-fim.json
```

The probe compares thinking modes and repeated synthetic prefixes. It records these items separately: first SSE event, reasoning, visible answer, failures and partial output. Empty-context TG128 does not predict long-context generation. See [measured results](ai-benchmarks.md) for the historical workstation experiment.

## Preparation

```bash
nacre ai prepare          # build and verify every declared artifact
nacre ai prepare build    # only the pinned llama.cpp
nacre ai prepare model    # only download and fully verify the declared models
```

- `build` builds the declared runtime and patches with native C++, ROCm and Vulkan tools. It installs them into a versioned directory and atomically selects that directory through `current`.
- `model` stages models by identity. It fully verifies SHA-256 before atomic publication and records a root-owned receipt.
- Routine deployment compares that identity and metadata. It does not hash the GGUF again.
- Resolve an unknown staging state, a selector mismatch or a checksum mismatch manually.
- Downloads use `hf download --local-dir`. To resume matching staged downloads, run `nacre ai prepare model` again. It verifies them before publication.

## Deploying and checking

```bash
nacre switch
curl --fail http://127.0.0.1:11434/v1/models
curl --fail http://127.0.0.1:11435/v1/models
sudo tailscale serve status --json
systemctl status llama-swap.service caddy.service
```

Before a build selector exists, deployment reports AI as unprepared and does not touch it. After preparation, these conditions stop convergence: missing models, invalid receipts, checksum drift, unmanaged Caddy state, service failures and post-preflight changes.

When you disable AI, Nacre withdraws management. Purge removes its Tailscale Serve route, Caddy site and llama-swap resources. It keeps prepared binaries, models and receipts.
