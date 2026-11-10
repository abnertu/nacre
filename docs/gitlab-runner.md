# GitLab Runner

Runner deployment is disabled by default. Public instance files expose a configured `#runnerctl` command even when deployment is disabled.

Nacre pins [gitlab-runnerctl v0.3.0](https://github.com/abnertu/gitlab-runner/releases/tag/v0.3.0) for deployment and configured operator commands.

## Public configuration

Declare public instance files in the machine configuration:

```nix
services.gitlabRunner.configFiles = [
  ./runners/frontend.toml
  ./runners/dotnet.toml
];
```

Each filename identifies an instance. The first file's directory bounds all selected files, shared `extends` bases and relative CA certificates.
Keep dependencies within that directory. Nacre copies only those public files and preserves their relative paths.
Never declare tokens, registration files or private keys. Read the [controller configuration format](https://github.com/abnertu/gitlab-runner#configure) for public TOML fields.

The configured package and app supply every declared file on every invocation. Flake checks validate the complete public configuration independently of deployment enablement.

```bash
nix run .#runnerctl -- validate
sudo nix run .#runnerctl -- status frontend
```

Disabled deployment does not inspect Runner state or capture its public-file closure. Selecting the configured output or its configuration check evaluates that closure.

## Deployment

Enable native reconciliation explicitly:

```nix
services.gitlabRunner.enable = true;
virtualization.enable = true;
virtualization.podman.enable = true;
```

Enabled deployment requires at least one instance file. The virtualization module owns shared Podman packages. The Runner module adds its remaining requirements.

Review `nacre plan` before deployment. Routine `switch` rejects missing packages. Use `nacre update` to install them before reconciliation.

Runner preflight inspects public policy without creating accounts, starting services or accessing registration contents.
Plans report unobserved runtime checks as deferred. Reconciliation rechecks every instance after package convergence and before its first Runner mutation.

The controller owns service accounts, subordinate IDs, sockets, units, images, locks and recovery markers.
Nacre runs declared instances in name order. Controller failures stop deployment before Home Manager activation.
An unreachable declared GitLab health endpoint fails reconciliation. Registration absence does not skip deployment.

## Runner role

Use `role = "runner"` on an existing Arch server or VM. This baseline enables Runner and Podman, with desktop and KVM tools disabled.
Machine defaults and ordinary definitions override the baseline. Disabling Podman while Runner remains enabled fails evaluation.

Supply host identity, an existing login account and public instance files in the machine configuration:

```nix
{ ... }:
{
  role = "runner";
  networking.hostname.name = "runner-host";
  deployment.username = "alice";
  users.users.alice = {
    homeDirectory = "/home/alice";
    stateVersion = "26.05";
    admin = true;
  };
  hardware.initramfs.images = [ "/boot/initramfs-linux.img" ];
  services.gitlabRunner.configFiles = [
    ./runners/frontend.toml
    ./runners/dotnet.toml
  ];
}
```

Prepare separate instance identities and nonoverlapping subordinate ranges in the public TOML files.
Use [installation](install.md) with repeated `--runner-config` flags to copy their public closure into a new machine checkout.
Review the plan before approving installation. `--yes` applies the plan and reconciles instances without registration.
Runner service accounts receive no Home Manager generation. The declared login account retains its home generation.

## Registration and recovery

Register each instance separately after GitLab becomes available:

```bash
sudo --preserve-env=GITLAB_RUNNER_TOKEN nix run .#runnerctl -- register frontend
sudo nix run .#runnerctl -- verify frontend
```

Supply tokens only through the controller's runtime interface. Nacre never registers instances during deployment.
Use `nacre --verbose switch` for public controller diagnostics. Keep pending markers when a command fails. Correct the reported cause and rerun deployment.

Disabling the feature or removing declarations only withdraws management.
Explicit `nacre purge` retires the currently declared Runner services and public policy through the controller.
Purge keeps accounts, subordinate allocations, registrations, images, caches and mutable data.
Stopping a managed service can remove its disposable manager container. Purge preserves stopped and unrelated containers.

## Migrating machine-owned integration

Remove duplicate machine-owned Runner option declarations, package contributions and wrappers when adopting this feature.
Retain public instance files and their dependencies.
Set `services.gitlabRunner.enable = false` to keep reconciliation separate from deployment.
Keep registrations and mutable state in their existing locations.
