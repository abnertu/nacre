# Local AI

The AI feature runs declared GGUF models with a pinned native llama.cpp, routed by llama-swap. Nix generates the routing, Caddy and systemd configuration; the Arch adapter checks prepared artifacts, ownership and service state before applying it. Built binaries and models live at declared native paths, outside the store.

```text
Tailnet HTTPS → Tailscale Serve → loopback Caddy → loopback llama-swap → loopback llama-server
```

Caddy forwards only `/health` and `/v1/*`. Models, profiles, versions and checksums are declared in the AI module.

## Selecting models

`programs.ai.llama.model.name` is the default model. With an empty `llama.models`, the single-model behavior applies; with explicit entries, every model you use (including `model.name`) must be enabled:

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

- Each model sets its own device, context, cache, batch, parallel slots and offload. The default model applies `llama.model` overrides first, then its per-model settings.
- Profiles share the model process and control only sampling and thinking.
- Unknown fields, profiles pointing at unselected models, invalid batches and conflicting thinking settings fail at evaluation.
- With concurrency, the selection may not exceed `maxLoadedModels`; backends load on first request and stay resident. Without it, the limit must be 1 and models swap on demand.
- Preparation covers selected models only; deselecting deletes nothing.

`vramEstimateMiB` and `memoryBudgetMiB` describe a measured budget: with a budget set, every selected model needs an estimate and the sum must fit. They do not limit real allocation. Fixed offload, context and batch with `fit = false` make results independent of load order. Measure peak prompt processing, leave headroom for the desktop and Sunshine, and remeasure after changing models or runtime.

The option name `qwen3.6-35b-a3b-ud-q5-k-m` is kept for compatibility; the file is MXFP4_MOE. Query `/v1/models` for exact API IDs.

## Agent skills

Home Manager installs explicitly selected skills as whole directory links in `~/.agents/skills` and `~/.gemini/config/skills`:

- the shared agent directory follows `programs.ai.enable` and `programs.ai.skillsPresets.enable`;
- the Antigravity directory follows `programs.ai.agy.enable` and `programs.ai.agy.skills.enable`;
- neither depends on llama.cpp preparation.

Sources and the selection live in [`modules/ai/skills.nix`](../modules/ai/skills.nix). The `matt-pocock-skills` and `vercel-skills` inputs are pinned in `flake.lock`; custom skills stay in this repository. Deployment uses the prebuilt sources from the activation package: no `npx`, no download at activation, no Skills CLI lock file.

Update skill sources after reviewing upstream changes:

```bash
nix flake update matt-pocock-skills vercel-skills
just check
just build
```

Then deploy and commit the lock change; revert the lock to roll back. `just arch-workstation update` handles native packages only and never advances skills. A selected upstream path that disappears or lacks `SKILL.md` fails evaluation, so updates never drop a skill silently. Fork an upstream skill into a custom one before modifying it; `npx skills update` would fight the managed links.

## Codex local profile

With AI, Codex and llama.cpp enabled, Home Manager generates `~/.codex/llama-cpp.config.toml` from the default model's API ID and context:

- provider `llama_cpp` (Responses API at `http://127.0.0.1:11434/v1`), web search off;
- auto-compaction at 75% of context (12K tokens at the default 16K);
- Codex multi-agent tools off, because the pinned llama.cpp Responses bridge supports only function tools.

Use it with `codex --profile llama-cpp` ([Codex 0.134+](https://learn.chatgpt.com/docs/config-file/config-advanced)). `--profile` reads from the default `~/.codex`, not a custom `CODEX_HOME`. Disable with `programs.ai.codex.localProfile.enable = false`. The module manages no other Codex settings or credentials.

Qwen3.5 uses a managed chat template that keeps multiple system/developer messages in order. The GGUF's built-in template rejects them with HTTP 500 (`System message must be at the beginning`), which Codex may show as a generic overload error.

## FIM completion

Base completion weights are served on `/v1/completions` with raw prefix/suffix tokens:

```bash
curl --fail http://127.0.0.1:11434/v1/completions \
  -H 'Content-Type: application/json' \
  --data '{"model":"Qwen2.5-Coder-3B-Q4_K_M.gguf","prompt":"<|fim_prefix|>def add(a, b):\n    <|fim_suffix|>\n\nassert add(2, 3) == 5\n<|fim_middle|>","max_tokens":64,"temperature":0,"stop":["<|fim_pad|>","<|endoftext|>","<|im_end|>"]}'
```

Set stop tokens explicitly; the candidate models declare different EOS tokens. Add a file or language hint to the prefix (for example `# Nix expression`) when the syntax is ambiguous.

## Benchmarks

These tools use the real GPU and are separate from deployment and checks. Download candidates to a scratch directory and verify their SHA-256. Avoid running another large model beside the managed router; for isolated runs, stop the router and restore it afterwards without touching `/etc`, receipts or the prepared selector.

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

It measures PP512, PP4096 and TG128 three times each and records binary version, model checksum, parameters, raw diagnostics and peak VRAM. `--depths 8192` measures generation after a longer prefix. The headroom monitor stops its own benchmark processes; polling cannot catch instant allocations.

```bash
python modules/ai/probe.py --base-url http://127.0.0.1:11434 \
  --model MODEL_ID --thinking-model MODEL_ID:thinking-coding \
  --output /var/tmp/ai-chat.json
python modules/ai/probe.py --base-url http://127.0.0.1:11434 \
  --model COMPLETION_ID --mode fim --output /var/tmp/ai-fim.json
```

The probe uses synthetic prompts, compares thinking on and off, and repeats prefixes to observe cache reuse. It records the first SSE event, reasoning and visible answer separately, including failures and partial output. Do not infer long-context speed from empty-context TG128. Results for this machine are in [benchmarks](ai-benchmarks.md).

## Preparation

```bash
just prepare-ai          # build and verify every declared artifact
just prepare-ai build    # only the pinned llama.cpp
just prepare-ai model    # only download and fully verify the declared models
```

- The build uses the declared llama.cpp version and reviewed patches, installs into a versioned directory, then atomically moves the `current` selector. It needs native C++, ROCm and Vulkan toolchains.
- Models are staged by declared identity, published atomically only after a full SHA-256 check, and recorded in a root-owned receipt. Routine deployment compares receipt identity and file metadata instead of rehashing the GGUF.
- Unknown staging state, a mismatched selector or checksum needs a manual decision.
- Downloads use `hf download --local-dir`. After a failed download, rerun `just prepare-ai model`: staging for the same identity is reused and still verified.

## Deploying and checking

```bash
just arch-workstation
curl --fail http://127.0.0.1:11434/v1/models
curl --fail http://127.0.0.1:11435/v1/models
sudo tailscale serve status --json
systemctl status llama-swap.service caddy.service
```

Until the build selector exists, deployment skips AI visibly and leaves its files and services alone. Afterwards, a missing model, invalid build or model receipt, checksum change, unmanaged Caddy configuration, failed service or state change after preflight stops the run.

Legacy standalone `llama-server` presets and drop-ins are recognized by their fixed historical content. Exact matches may stay during the migration to llama-swap; modified ones need explicit adoption. Nothing is removed automatically.

Disabling AI stops convergence and removes nothing. `purge` withdraws the Tailscale Serve route, the Caddy site and `llama-swap`, keeping prepared binaries, models and receipts.
