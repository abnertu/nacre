# GitLab Runner

Each Runner instance is a TOML file named after its environment: `hosts/arch/runners/frontend.toml` declares the `frontend` instance, run by the `gitlab-runner-frontend` account. Shared GitLab and network settings live in `common.toml`, which instance files reference with `extends`. `services.gitlabRunner.configFiles` lists the managed files; adding or removing a file adds or removes an instance. The format is described in the [runnerctl README](https://github.com/gin31259461/gitlab-runner#configure).

Each instance has its own service account, sub-UID/GID range, rootless Podman, manager container, user service and GitLab registration. `runnerctl` validates the file set, renders templates, configuration and user units, and owns account and runtime convergence, registration and token merging. It does not need Nix; this repository pins its version and passes the files. Tokens never enter Git or the store.

Runner operations are separate from `just arch-workstation`, which installs the declared native dependencies on `update` but never converges or registers instances.

## Converge

```bash
just prepare-runner frontend
```

Checks the required network interfaces, the dedicated account, sub-ID ranges and the rootless Podman socket, then prepares directories, configuration, the manager image and the user service. It refuses conflicts instead of replacing another owner's resources, and creates no registration. The manager reaches only its own rootless socket; jobs run unprivileged in their own network without access to it.

## Register (once)

Create a Runner in GitLab and pass its authentication token only through this command's environment:

```bash
read -rsp 'GitLab Runner token: ' GITLAB_RUNNER_TOKEN
export GITLAB_RUNNER_TOKEN
just initialize-runner frontend
unset GITLAB_RUNNER_TOKEN
```

Convergence must succeed first; a different existing registration is refused. The token passes through sudo only during registration, and sensitive output is hidden.

## Verify and recover

```bash
just verify-runner frontend
just status-runner frontend
```

Verify checks the registration, service, manager image and mount isolation, socket, GitLab health and a one-off job network. Status prints a summary without sensitive data. All operations share `/run/lock/nix-config-runner.lock`; managed writes refuse symlinks, hard links and unexpected file types. An interrupted convergence or credential step leaves a private pending marker in the instance config directory; fix the cause and rerun. Removing a file from `configFiles` stops management and dependency installation but deletes no runtime state.

`just check` runs `runnerctl validate` on the declared files.
