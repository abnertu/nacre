# Personal Agent

`services.personalAgent.enable` deploys the pinned `personal-agent` flake package. That repository owns the application and its dependencies; this one owns the Arch account, native directories, the generated unit and service convergence. Runtime configuration and the database stay out of Git and the store.

Provide these outside the repository:

| Path | Contents | Owner and mode |
| --- | --- | --- |
| `/etc/personal-agent/config.toml` | Application identity and inference settings | `root:personal-agent`, `0640` |
| `/etc/personal-agent/agent.env` | Secret tokens | `root:root`, `0600` |
| `/var/lib/personal-agent/` | Database | — |

Deployment checks that these exist with the right metadata and never prints their contents.

Before the first setup the module may skip as `not ready`. Afterwards, missing or unsafe configuration is runtime drift and stops the run. Update the application by updating its input:

```bash
nix flake update personal-agent
just check
just build
```

## Operating the service

```bash
sudo systemctl status personal-agent.service
sudo journalctl -u personal-agent.service -f
```

Disabling the declaration withdraws management only. Workstation purge removes the managed unit and stops the service, keeping the account, configuration and database.
