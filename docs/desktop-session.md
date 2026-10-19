# Desktop session

UWSM starts Hyprland and owns the graphical session. Arch provides native binaries; Home Manager provides user configuration and user services. Each application has one startup owner. Desktop and user switches in `configuration.nix` decide what the next home generation contains; disabling one does not delete application data.

- Noctalia owns the StatusNotifier watcher; tray applications start after it.
- Vicinae starts in a degraded mode if the watcher is late.
- Vesktop's compatibility flags live in its own service.
- Sunshine captures through Wayland `wlr`.
- Activation starts new user units, restarts changed ones and stops removed ones; unchanged units keep running.
- The dev profile uses `pass` through `programs.password-store`, with GPG and the Git credential helper.

## Themes

Home Manager owns each application's configuration; Noctalia owns its colors. The configuration points at a theme file that Noctalia's templates write at runtime and rewrite when the wallpaper changes:

| Application | Theme file Noctalia writes |
| --- | --- |
| Kitty | `kitty/themes/noctalia.conf` |
| Ghostty | `ghostty/themes/noctalia` |
| GTK 3 / 4 | `gtk-3.0/noctalia.css`, `gtk-4.0/noctalia.css` |
| Qt (qt5ct / qt6ct, Fusion style) | `qt5ct/colors/noctalia.conf`, `qt6ct/colors/noctalia.conf` |
| btop, cava | `btop/themes/noctalia.theme`, `cava/themes/noctalia` |
| Vesktop | `vesktop/themes/noctalia*.css`, `discord-system24.css` |
| Hyprland | `hypr/noctalia.lua` (only in a local worktree; the pinned config keeps its committed theme) |

The templates are selected in the Noctalia snapshot. Theme files are not in the repository: on a new machine they appear once Noctalia first runs. Noctalia's Kitty hook cannot touch the read-only `kitty.conf`, so the `kitty-theme-reload` user path unit watches the theme file and signals running Kitty windows to reload.

## Application settings

Some applications rewrite their own settings files. Nacre manages each one by how its settings change:

- **Changed rarely, on purpose: declared read-only.** fcitx5's input methods and global options come from `workstation.fcitx5` in the home configuration, and `~/.config/fcitx5` is a read-only link: `fcitx5-configtool` cannot save, so change the options and switch. Only values that differ from fcitx5's defaults belong there. Learned phrases stay writable in `~/.local/share/fcitx5`. If `~/.config/fcitx5` already exists as a directory, activation stops; move it aside once.
- **Changed often in the application: reviewed snapshot.** Noctalia keeps GUI changes live and the repository keeps a snapshot; `nacre doctor` reports uncaptured changes, and [`nacre noctalia capture`](noctalia-config.md#capture) brings them into the checkout for review.

## Noctalia encrypted storage

Noctalia's file-based encrypted storage uses `~/.local/share/noctalia/file-key-v1/master-key`, outside Git and the store. Home Manager activation generates a key when none exists, so **redeploying after losing the key creates a new one and the old encrypted data becomes unreadable**. Back it up with the data it protects; see [backup](backup.md).

## Checking the session

```bash
systemctl --user is-active noctalia.service
busctl --user call org.freedesktop.DBus /org/freedesktop/DBus \
  org.freedesktop.DBus GetConnectionUnixProcessID s org.kde.StatusNotifierWatcher
systemctl --user show noctalia.service -p MainPID
```

The watcher PID should belong to Noctalia. Restarting the shell should not require restarting unrelated applications to recover the tray.

## Live development

Neovim and Hyprland configuration default to pinned flake inputs (`nvim-config`, `hypr-config`) that Home Manager projects into `~/.config/nvim` and `~/.config/hypr`, after checking it will not overwrite a Git worktree or a backup directory.

To use your own published configuration, add it as an input of the machine flake and pass it in `flake.nix`:

```nix
outputs = { nacre, ... }@inputs: nacre.lib.mkFlake {
  modules = [
    ./configuration.nix
    { users.users.alice.sources.hyprland = inputs.my-hypr; }
  ];
};
```

`sources.neovim` does the same for Neovim.

To edit a local worktree without rebuilding, set absolute paths in `configuration.nix`:

```nix
users.users.abnertu.development = {
  neovimPath = "/home/abnertu/path/to/nvim-config";
  hyprlandPath = "/home/abnertu/path/to/hypr-config";
};
```

Home Manager then links the target straight to that path with `mkOutOfStoreSymlink` and skips the worktree check for it. Edits apply when the editor or compositor reloads. Set the path back to `null` to return to the pinned input and the full check.

Keybindings and Hyprland appearance live in the Hyprland repository; see its README. Noctalia's wallpaper, bar and widgets are covered in [Noctalia config](noctalia-config.md).
