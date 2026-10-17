# 組合模型

這個 repo 描述一台既有的 Arch Linux 工作站：由 Nix 評估設定，再分兩層實現。Nix 建置一個不可變的部署產物，內含選定的 Home Manager 啟用套件；Arch 轉接器先收斂原生檔案、套件與服務，再啟用那個固定的 home 世代。

| 邊界 | 擁有者 | 責任 |
| --- | --- | --- |
| 公開設定 | `configuration.nix`、`lib/configuration-options.nix`、`modules/` 下的功能模組 | 型別化選項、預設值、assertion 與原生資源貢獻 |
| Host | `hosts/` | 身分、使用者、硬體與功能基準 |
| 原生平台 | `platforms/arch/` | Arch 套件、產生的設定、特權收斂 |
| Home | `profiles/`、`homes/`、home 模組 | 使用者套件、受管理的靜態檔案與 user service |
| 外部執行環境 | 使用者與各功能的準備指令 | 機密、可變資料、原生建置與模型下載 |

`configuration.nix` 匯入選定的 Host。Host 基準使用 `lib.mkDefault`，一般定義可直接覆寫，不依賴匯入順序。`lib/eval-configuration.nix` 評估明確的功能清單（`modules/default.nix`）與平台模組，檢查跨欄位 assertion，並整理成內部使用的資料。功能模組把原生套件、群組與 unit 貢獻到內部的 `arch` 選項，由 `lib/mk-deployment.nix` 交給 Arch 實現。清單一律明確列出；每個套件、帳號、檔案或服務只有一個擁有者。

## 靜態設定與即時收斂

Nix 產生固定內容，例如 Home Manager 檔案、systemd unit、drop-in 與 AI 路由和 Caddy 設定。依賴當下機器狀態的工作由原生轉接器負責：安全接管既有檔案、檢查所有權與權限、帳號與服務狀態、鎖、pending 標記、套件操作與失敗回報。GitLab Runner 以各環境的 TOML 檔宣告，由鎖定版本的 `runnerctl` 自行驗證與產生設定；token 只在執行時合併，token 與可變的註冊都不進入 derivation。

這種分工借用了 [nix-maid](https://viperml.codeberg.page/nix-maid/api.html) 宣告式產生檔案的概念，但沒有把它加為依賴或第二層 Home Manager：功能模組擁有產生的內容，轉接器保留 Arch 專屬的收斂。

上游 agent skill 是由獨立 flake input 鎖定的不可變來源。AI 模組明確選取，Home Manager 把完整的 skill 目錄投射到 home；只有自訂 skill 寫在這個 repo。更新來源版本只會改變下一個建置的 home 世代，沒有執行時安裝器，也沒有第二個擁有者。見 [skill 的部署與更新](docs/ai.md#agent-skills)。

Home Manager 通常以連到 store 的連結實現靜態 home 檔案；Arch 原生檔案則以原生的擁有者與權限複製或合併進 `/etc`。已準備的 llama.cpp 執行檔與 GGUF 模型留在 store 之外。Hyprland 與 Neovim 的原始碼也不在受管理的執行路徑內：預設以外部 flake input 鎖定，或透過使用者的 `development` 選項（`development.neovimPath`、`development.hyprlandPath`）以 out-of-store symlink 投射本機 worktree。

## 部署流程

1. 建置部署產物與其中固定的 Home Manager 世代。
2. 預檢 Arch 身分、套件、核心原生狀態與可選模組是否就緒。
3. 只有 `--update` 時收斂套件，接著收斂原生檔案與服務。
4. 收斂已準備好的可選模組。
5. 啟用固定的 home 世代。

核心失敗會中止部署。可選模組只有在從未完成準備時才能回報 `not ready`；無效的收據、checksum 不符、所有權衝突、指令失敗與之後的狀態漂移都是錯誤。Arch 與 Home Manager 沒有共同的回滾。pending 標記在原生變更前記錄，成功後才清除。停用 Arch 宣告只是不再管理；明確 purge 的範圍較窄，見[部署](docs/deployment.md)。

AI 準備與 Runner 註冊是獨立的生命週期，操作見 [AI 指南](docs/ai.md) 與 [Runner 指南](docs/runners.md)。變更規則在 [AGENTS.md](AGENTS.md)，入口是 [README.md](README.md)。
