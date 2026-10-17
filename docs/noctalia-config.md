# Noctalia 設定

`noctalia-config` 在 Noctalia 的實際設定與 repo 內的快照 `homes/abnertu/noctalia/config.toml` 之間同步審閱過的 UI 偏好，Home Manager 管理對應的連結。它不管加密儲存的金鑰或應用資料，那些見[桌面工作階段](desktop-session.md)。

這份快照是 Noctalia 視覺偏好的唯一來源，`wallpaper` 區段也可以擷取與部署。在 GUI 選桌布會寫入一個覆寫，優先於宣告的預設值；`deploy --dry-run` 會偵測衝突，下方的 `--replace-overrides` 流程只在 Noctalia 停止時清除自己擁有的區段。

Hyprland 的配色範本保持啟用，供本機開發 worktree 使用。其他應用程式的範本是停用的，因為 Kitty、Ghostty、GTK 與 Qt 的設定由 Home Manager 管理，repo 內的終端機主題提供固定配色；要啟用範本，需要可寫的輸出路徑並明確變更擁有者。所以換桌布後，要目視確認 Noctalia 配色與終端機主題。

不讀取實際狀態、只驗證原始碼：

```bash
noctalia config validate homes/abnertu/noctalia/config.toml
```

## 擷取快照

在這個 checkout 執行：

```bash
nix run .#noctalia-config -- capture --dry-run
nix run .#noctalia-config -- capture
nix run .#noctalia-config -- capture --skip-themes
```

擷取會匯出實際生效的設定，只保留自己擁有的 UI 區段，驗證暫存的候選檔，內容不同時才以原子方式更新快照。它也會依目前的桌布與配色，同步 `files/home/.config/` 下的終端機與應用程式主題（`--skip-themes` 只擷取 TOML）。它不會 stage、commit 或 push。commit 前先看 diff，標籤、路徑等值可能含個人資訊。驗證出現警告時擷取會停止；要在本機檢查實際設定，執行 `/usr/bin/noctalia config validate`，輸出含個人資訊時不要外流。

內建配色使用 repo 內的 [Noctalia 5.1 配色目錄](../modules/home/noctalia-config/builtin-palettes.json)，來源是[上游 `builtin_palettes.cpp`](https://github.com/noctalia-dev/noctalia/blob/v5.1.0/src/theme/builtin_palettes.cpp)，不依賴社群配色快取。升級 Noctalia 後，擷取內建主題前先依對應版本更新這份目錄。

## 部署

```bash
nix run .#noctalia-config -- deploy --dry-run
nix run .#noctalia-config -- deploy
```

部署會建置並啟用選定的 Home Manager 設定，再驗證受管理的 Noctalia 區段；不執行 Arch 收斂。世代在啟用前就已固定。GUI 的覆寫與設定衝突時部署會停止。要刻意取代自己擁有的覆寫區段，先停止 Noctalia：

```bash
systemctl --user stop noctalia.service
nix run .#noctalia-config -- deploy --replace-overrides
systemctl --user start noctalia.service
```

不屬於它的區段不會被修改。變更覆寫前會先寫入私有的復原狀態；它不會自動停止服務。

## 復原與驗證

復原狀態在 `~/.local/state/nix-config/noctalia-config/`。取代被中斷時，保留收據與備份，停止 Noctalia 後執行：

```bash
nix run .#noctalia-config -- deploy --recover
```

只有在目前狀態仍符合紀錄的轉換時，才會還原保存的內容；同時有其他修改時需要手動處理。原始碼測試使用暫存的 home 與假指令：

```bash
nix build --no-link --show-trace --print-build-logs \
  .#checks.x86_64-linux.noctalia-config .#noctalia-config
just check
```
