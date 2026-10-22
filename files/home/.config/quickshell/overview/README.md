# Quickshell workspace overview

Hyprland workspace grid with live previews, keyboard navigation and window drag and drop.

![Overview screenshot](assets/image.png)

## Usage

Enable `desktop.overview.enable` and activate the home generation. The graphical-session module owns `quickshell-overview.service`; Home Manager projects this directory.

```bash
qs ipc -c overview call overview toggle
qs ipc -c overview call overview open
qs ipc -c overview call overview close
```

Click to focus a window, middle-click to close it, or drag it between workspaces. Arrow keys navigate; Escape and Enter close the overview.

Edit `common/Config.qml` for grid size and scale and `common/Appearance.qml` for appearance, then activate the next home generation. Validate refresh behaviour with `nix build --no-link .#checks.x86_64-linux.overview-refresh`.

Adapted from end-4's [illogical-impulse](https://github.com/end-4/dots-hyprland) and [quickshell-overview](https://github.com/Shanu-Kumawat/quickshell-overview). Preserve upstream attribution when redistributing.
