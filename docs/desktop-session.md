# 桌面工作階段

UWSM 啟動 Hyprland 並擁有圖形工作階段。Arch 提供原生執行檔，Home Manager 提供使用者設定與 user service。每個應用程式只有一個啟動來源。`configuration.nix` 裡的桌面與使用者開關決定下一個 home 世代包含哪些內容；停用不會清除應用資料。

- Noctalia 擁有 StatusNotifier watcher，系統匣程式在它之後啟動。
- watcher 延遲時，Vicinae 會在有限時間內降級啟動。
- Vesktop 的相容性參數放在它自己的 service。
- Sunshine 使用 Wayland `wlr` 擷取。
- dev profile 透過 `programs.password-store` 使用 `pass`，搭配 GPG 與 Git credential helper。

確切的套件與 unit 以各自的模組為準。

## Noctalia 加密儲存

Noctalia 的檔案式加密儲存使用 `~/.local/share/noctalia/file-key-v1/master-key`，不在 Git 也不在 Nix store。Home Manager 啟用時，金鑰不存在就自動產生一把新的；所以**金鑰遺失後重新部署，會得到新金鑰，舊的加密資料將無法讀取**。這把金鑰要和它保護的資料一起備份，見[備份清單](backup.md)。

## 檢查工作階段

```bash
systemctl --user is-active noctalia.service
busctl --user call org.freedesktop.DBus /org/freedesktop/DBus \
  org.freedesktop.DBus GetConnectionUnixProcessID s org.kde.StatusNotifierWatcher
systemctl --user show noctalia.service -p MainPID
```

watcher 的 PID 應該屬於 Noctalia。重啟 shell 時，不應為了恢復系統匣而重啟無關的應用程式。偏好設定的擷取與部署見 [Noctalia 設定](noctalia-config.md)。原始碼測試使用合成的 Home Manager 設定與假指令，`just check` 不會連到實際的桌面。

## 即時開發模式

Neovim 與 Hyprland 設定預設是 `flake.nix` 裡鎖定版本的 input（`nvim-config`、`hypr-config`），由 Home Manager 投射到 `~/.config/nvim` 與 `~/.config/hypr`，並在啟用前檢查不會覆蓋 Git worktree 或備份目錄。

要直接編輯本機 worktree、不必重建 store 也不被預檢擋下，在 `configuration.nix` 設定絕對路徑：

```nix
users.users.abnertu.development = {
  neovimPath = "/home/abnertu/path/to/nvim-config";
  hyprlandPath = "/home/abnertu/path/to/hypr-config";
};
```

設定後：

- Home Manager 用 `mkOutOfStoreSymlink` 直接連到該路徑，而不是鎖定版本的 store 路徑。
- 該目標略過 worktree 保護檢查。
- 本機修改在編輯器或視窗管理器重新載入時立即生效，不需 `just arch-workstation`。
- 設回 `null`（或不設定）即恢復鎖定版本與完整的保護檢查。

Hyprland 的外觀、固定工作區 1–5、Noctalia 圖層模糊與 `SUPER+SHIFT+P` 控制中心快捷鍵在外部的 Hyprland worktree，按鍵說明見它自己的 README。Noctalia 的桌布、工作列與小工具見 [Noctalia 設定](noctalia-config.md)。重新載入 compositor 是另一個手動動作。
