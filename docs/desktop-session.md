# Desktop session

UWSM starts Hyprland and owns the graphical session. Arch provides native binaries; Home Manager provides user configuration and user services. Each application has one startup owner. Desktop and user switches in `configuration.nix` decide what the next home generation contains; disabling one does not delete application data.

- Noctalia owns the StatusNotifier watcher; tray applications start after it.
- Vicinae starts in a degraded mode if the watcher is late.
- Vesktop's compatibility flags live in its own service.
- Sunshine captures through Wayland `wlr`.
- The dev profile uses `pass` through `programs.password-store`, with GPG and the Git credential helper.

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

To edit a local worktree without rebuilding, set absolute paths in `configuration.nix`:

```nix
users.users.abnertu.development = {
  neovimPath = "/home/abnertu/path/to/nvim-config";
  hyprlandPath = "/home/abnertu/path/to/hypr-config";
};
```

Home Manager then links the target straight to that path with `mkOutOfStoreSymlink` and skips the worktree check for it. Edits apply when the editor or compositor reloads. Set the path back to `null` to return to the pinned input and the full check.

Keybindings and Hyprland appearance live in the Hyprland repository; see its README. Noctalia's wallpaper, bar and widgets are covered in [Noctalia config](noctalia-config.md).
