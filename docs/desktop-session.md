# Desktop session

UWSM starts Hyprland. Arch provides native graphical binaries. Home Manager supplies configuration and user services. Each application has one startup owner. Activation starts new units, restarts changed units and stops removed units. Unchanged services continue to run.

Noctalia owns the StatusNotifier watcher. Tray applications wait for it. Vicinae accepts a late watcher. Vesktop keeps compatibility flags in its own service. Sunshine captures through Wayland `wlr`. The development profile uses GPG-backed `pass` for password storage and Git credentials.

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

Select templates in the Noctalia snapshot. The files appear after the first Noctalia run and follow the wallpaper. The pinned Hyprland input keeps its committed theme. The default Ghostty, btop and cava configuration already selects these files. A replacement configuration must also select them. Then hooks can reload programs without edits to read-only declarations.

## Application settings

fcitx5 uses read-only declarations under `workstation.fcitx5`. Change input methods and global options in the home configuration, then switch. The fcitx5 GUI cannot save them. Declare only non-default values. Learned phrases stay writable under `~/.local/share/fcitx5`. An existing configuration directory blocks activation. Move it aside deliberately.

Noctalia keeps live GUI preferences and a reviewed snapshot in the machine flake. Doctor reports drift. [Capture](noctalia-config.md#capture) imports intended changes for review.

## Noctalia encrypted storage

The Noctalia file storage key lives outside Git and the store, at `~/.local/share/noctalia/file-key-v1/master-key`. Activation generates a missing key. Encrypted data that you restore without its original key is unreadable. Back up the key and the data together, as the [backup guide](backup.md) describes.

## Checking the session

```bash
systemctl --user is-active noctalia.service
busctl --user call org.freedesktop.DBus /org/freedesktop/DBus \
  org.freedesktop.DBus GetConnectionUnixProcessID s org.kde.StatusNotifierWatcher
systemctl --user show noctalia.service -p MainPID
```

The watcher PID must belong to Noctalia. A shell restart must recover the tray without a restart of unrelated applications.

## Live development

Home Manager projects pinned `nvim-config` and `hypr-config` inputs into `~/.config/nvim` and `~/.config/hypr`. Projection does not overwrite a Git worktree or a backup directory.

To use another published source, add it as a machine flake input. Then select it:

```nix
outputs = { nacre, ... }@inputs: nacre.lib.mkFlake {
  modules = [
    ./configuration.nix
    { users.users.alice.sources.hyprland = inputs.my-hypr; }
  ];
};
```

Use `sources.neovim` for Neovim. For edits without a rebuild, choose absolute local paths:

```nix
users.users.alice.development = {
  neovimPath = "/home/alice/src/orbitvim";
  hyprlandPath = "/home/alice/src/hypr";
};
```

Home Manager links directly to each worktree and skips the projection check of that target. To apply edits, reload the editor or compositor. To restore the pinned source and projection checks, set the path to `null`.

Bindings and compositor appearance belong in the Hyprland repo. Wallpaper, bar and widgets belong in [Noctalia configuration](noctalia-config.md).
