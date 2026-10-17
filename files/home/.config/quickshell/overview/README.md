# Quickshell workspace overview

A Hyprland workspace overview with live window previews, keyboard navigation and drag and drop. Home Manager projects this directory into the home; the graphical-session module owns `quickshell-overview.service`.

![Overview screenshot](assets/image.png)

## Usage

With `desktop.overview.enable` set and the home generation active, the user service starts the overview. IPC:

```bash
qs ipc -c overview call overview toggle
qs ipc -c overview call overview open
qs ipc -c overview call overview close
```

Click a window to focus it, middle-click to close, drag windows between workspaces, navigate with arrow keys, close with Escape or Enter. Grid size and scale are in `common/Config.qml`, appearance in `common/Appearance.qml`; edit them here and activate the next home generation.

Validate source:

```bash
nix build --no-link .#checks.x86_64-linux.overview-refresh
```

Adapted from the overview in end-4's [illogical-impulse](https://github.com/end-4/dots-hyprland) and the standalone [quickshell-overview](https://github.com/Shanu-Kumawat/quickshell-overview). Keep upstream attribution when redistributing.
