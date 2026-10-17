# Quickshell 工作區總覽

Hyprland 的工作區總覽：顯示各工作區與即時視窗預覽，支援鍵盤導覽與拖放。原始碼在 `files/home/.config/quickshell/overview/`，由 Home Manager 投射到使用者的 home；`quickshell-overview.service` 由 graphical-session 模組負責。不要在受管理的執行路徑另外 clone 一份，也不要再加一個 Hyprland 啟動項目。

![總覽截圖](assets/image.png)

## 使用

選取 `desktop.overview.enable` 並啟用 home 世代後，UWSM 與 user service 會啟動總覽。IPC 控制：

```bash
qs ipc -c overview call overview toggle
qs ipc -c overview call overview open
qs ipc -c overview call overview close
```

點擊視窗切換焦點、中鍵關閉、在工作區之間拖放視窗、方向鍵導覽、Escape 或 Enter 關閉。網格大小與縮放改 `common/Config.qml`，外觀改 `common/Appearance.qml`，再建置並啟用下一個 home 世代；只改受管理執行路徑的內容會在啟用時被覆蓋。

## 驗證原始碼

```bash
nix build --no-link --show-trace --print-build-logs \
  .#checks.x86_64-linux.overview-refresh
```

查詢與重新整理的測試使用假訊號，並確認原生查詢失敗時保留最後一次的有效狀態。更大範圍的工作階段行為由 `just check` 與[桌面工作階段](../../../../../docs/desktop-session.md)涵蓋。

改寫自 end-4 的 [illogical-impulse](https://github.com/end-4/dots-hyprland) 總覽與獨立的 [quickshell-overview](https://github.com/Shanu-Kumawat/quickshell-overview) 專案，再散布時請保留上游的出處。
