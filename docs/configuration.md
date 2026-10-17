# Configure the workstation

Edit `configuration.nix` to override the selected Host. Its import of `hosts/arch` supplies reviewed machine defaults through `lib.mkDefault`; ordinary definitions in `configuration.nix` take precedence. Import order never supplies precedence. The public schema and feature interfaces reject unknown options, wrong types and invalid combinations during evaluation.

```nix
{ ... }:
{
  imports = [ ./hosts/arch ];
  networking.firewall.enable = false;
  services.fstrim.enable = false;
  time.timeZone = "UTC";
}
```

Inspect the normalized result before building or activating:

```bash
nix eval .#lib.configurations.arch.networking.hostname.name
nix eval .#lib.configurations.arch.services.fstrim.enable
nix eval --json .#lib.configurations.arch.networking.firewall
```

`lib/configuration-options.nix` and feature modules under `modules/` own option types; `lib/configuration-assertions.nix` holds cross-field rules; `lib/eval-configuration.nix` produces private Host and adapter values. `hosts/arch` owns machine defaults and user identity. `profiles/`, `homes/` and home modules own reusable and user-specific Home Manager composition.

## Pick the correct owner

| Change | Public namespace or owner |
| --- | --- |
| Network, hotspot, firewall and hostname | `networking` |
| Locale, timezone and console | `i18n`, `time`, `console` |
| Native services, AI, Runners and Personal Agent | `services`, `programs.ai` and their feature interfaces |
| Hardware and virtualization | `hardware`, `virtualization` |
| Kernel modules and parameters | `boot.kernelModules`, `boot.kernel.sysctl` |
| Graphical session and user programs | `desktop`, `programs`, `users.users.<name>.home` |

Parent capability switches gate their owned resources. A disabled Arch capability withdraws future management; it does not uninstall a package, retire a service, remove a registration or erase application state. Home Manager applies the next selected generation through its normal transition. An enabled optional module that has never completed required preparation may report `not ready`; invalid prepared state is an error.

`boot.kernelModules` and `boot.kernel.sysctl` default to the container networking baseline (bridge modules, forwarding, BBR). Override a single parameter by key, set it to `null` to withdraw it, or replace the module list with `lib.mkForce`.

AI selection lives under `programs.ai.llama.models.<inventory-key>`;
`model.name` selects the default agent, while `concurrentModels` and
`maxLoadedModels` control residency. Each model owns runtime settings; profiles
own request sampling and thinking. Optional `memoryBudgetMiB` validates the sum
of per-model `vramEstimateMiB` values without enforcing an allocator cap. Read
the [AI guide](ai.md) before changing models, offload or context sizes.
When AI, Codex and llama.cpp are enabled, `programs.ai.codex.localProfile.enable`
(default `true`) manages `~/.codex/llama-cpp.config.toml` for `codex --profile
llama-cpp`. Disable it to withdraw management of that file.

## User and home selection

The default Host selects its existing human account through `deployment.username`. The account must exist on the machine before deployment. For a different login user, change both the selected account and the declared user identity in `configuration.nix`; [Host users](../hosts/arch/users.nix) are the baseline to adapt. Keep reusable home behavior in `profiles/` or home modules and machine-specific differences in `homes/` or the Host. Service accounts are owned by their modules and do not get a human home configuration. Do not bump Home Manager `stateVersion` as a routine update.

Validate the result with `just check-fast`, `just check` and `just build`. Read [deployment](deployment.md) before activating and [system settings](system-settings.md) before changing native ownership.
