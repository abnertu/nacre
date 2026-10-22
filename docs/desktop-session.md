# Desktop session

UWSM starts Hyprland. Arch provides native graphical binaries; Home Manager supplies configuration and user services. Each application has one startup owner. Activation starts new units, restarts changed units and stops removed units while leaving unchanged services running.

Noctalia owns the StatusNotifier watcher. Tray applications wait for it; Vicinae tolerates a late watcher. Vesktop keeps compatibility flags in its own service, and Sunshine captures through Wayland `wlr`. The development profile uses GPG-backed `pass` for password storage and Git credentials.

## Themes

Application configuration selects theme files that Noctalia rewrites at runtime:

| Application | File under the XDG configuration directory |
| --- | --- |
| Ghostty | `ghostty/themes/noctalia` |
| GTK 3 / 4 | `gtk-3.0/noctalia.css`, `gtk-4.0/noctalia.css` |
| qt5ct / qt6ct, Fusion style | `qt5ct/colors/noctalia.conf`, `qt6ct/colors/noctalia.conf` |
| btop / cava | `btop/themes/noctalia.theme`, `cava/themes/noctalia` |
| Vesktop | `vesktop/themes/noctalia*.css`, `discord-system24.css` |
| Hyprland | `hypr/noctalia.lua`, writable only with a local worktree |

Select templates in the Noctalia snapshot. Files appear after Noctalia first runs and follow the wallpaper. The pinned Hyprland input retains its committed theme. Default Ghostty, btop and cava configuration already selects these files; replacement configuration must do the same so hooks can reload programs without editing read-only declarations.

## Application settings

fcitx5 uses read-only declarations under `workstation.fcitx5`. Change input methods and global options in the home configuration and switch; its GUI cannot save them. Declare only non-default values. Learned phrases remain writable under `~/.local/share/fcitx5`. An existing configuration directory blocks activation and must be moved aside deliberately.

Noctalia keeps GUI preferences live and a reviewed snapshot in the machine flake. Doctor reports drift; [capture](noctalia-config.md#capture) imports intended changes for review.

## Noctalia encrypted storage

Noctalia's file storage key lives outside Git and the store at `~/.local/share/noctalia/file-key-v1/master-key`. Activation generates a missing key. Restoring encrypted data without its original key makes that data unreadable; back up both together using the [backup guide](backup.md).

## Checking the session

```bash
systemctl --user is-active noctalia.service
busctl --user call org.freedesktop.DBus /org/freedesktop/DBus \
  org.freedesktop.DBus GetConnectionUnixProcessID s org.kde.StatusNotifierWatcher
systemctl --user show noctalia.service -p MainPID
```

The watcher PID should belong to Noctalia, and restarting the shell should recover the tray without restarting unrelated applications.

## Live development

Home Manager projects pinned `nvim-config` and `hypr-config` inputs into `~/.config/nvim` and `~/.config/hypr`. Projection refuses to overwrite a Git worktree or backup directory.

To use another published source, add it as a machine flake input and select it:

```nix
outputs = { nacre, ... }@inputs: nacre.lib.mkFlake {
  modules = [
    ./configuration.nix
    { users.users.alice.sources.hyprland = inputs.my-hypr; }
  ];
};
```

Use `sources.neovim` for Neovim. For edits without rebuilding, choose absolute local paths:

```nix
users.users.alice.development = {
  neovimPath = "/home/alice/src/orbitvim";
  hyprlandPath = "/home/alice/src/hypr";
};
```

Home Manager links directly to each worktree and skips that target's projection check. Reload the editor or compositor to apply edits. Set the path to `null` to restore the pinned source and projection checks.

Bindings and compositor appearance belong in the Hyprland repository. Wallpaper, bar and widgets belong in [Noctalia configuration](noctalia-config.md).
