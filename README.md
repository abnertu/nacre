# nix-config

[![Check](https://img.shields.io/github/actions/workflow/status/gin31259461/nix-config/check.yml?branch=main&label=check&logo=githubactions&logoColor=white)](https://github.com/gin31259461/nix-config/actions/workflows/check.yml)
[![Arch Linux](https://img.shields.io/badge/Arch_Linux-1793D1?logo=archlinux&logoColor=white)](https://archlinux.org/)
[![Hyprland](https://img.shields.io/badge/Hyprland-58E1FF?logo=hyprland&logoColor=black)](https://hypr.land/)
[![Nix Flakes](https://img.shields.io/badge/Nix_Flakes-5277C3?logo=nixos&logoColor=white)](https://nixos.org/)
[![Home Manager](https://img.shields.io/badge/Home_Manager-26.05-5277C3?logo=nixos&logoColor=white)](https://nix-community.github.io/home-manager/)

以 Nix 與 Home Manager 宣告式管理的 Arch Linux + Hyprland 工作站設定。

Nix 評估型別化設定並建置固定的部署產物；Arch 轉接器先收斂系統檔案、套件與服務，再啟用同一份 Home Manager 世代。平台邏輯獨立於 `platforms/`，目前支援 Arch Linux（`x86_64-linux`），之後可擴充到其他發行版。本專案不是 NixOS 設定，也不是系統安裝器。

![桌面預覽](docs/assets/preview.png)

## 特色

- **Hyprland 桌面**：以 UWSM 啟動，Noctalia shell，每個應用只有一個啟動來源。
- **型別化設定**：未知欄位、錯誤型別與無效組合在評估階段就失敗。
- **安全部署**：先預檢再變更；日常部署不安裝套件，只有 `update` 會同步 pacman 與 AUR。
- **可選模組**：本機 AI（llama.cpp + llama-swap）、虛擬化、GitLab Runner、Personal Agent、熱點等。
- **機密分離**：憑證、金鑰與可變資料不進 Git，也不進 Nix store。

## 需求

- Arch Linux `x86_64`，且部署使用者帳號已存在
- 已啟用 flakes 的 [Nix](https://nixos.org/download/) 與 [just](https://just.systems/)

全新安裝的 Arch 尚未有 Nix 或 just 時，先執行 [bootstrap](docs/deployment.md#bootstrap)。

## 快速開始

```bash
git clone https://github.com/gin31259461/nix-config ~/.config/nix
cd ~/.config/nix
```

調整 [configuration.nix](configuration.nix)（預設值在 [hosts/arch](hosts/arch/default.nix)），再驗證並建置。這些指令不會改動系統：

```bash
just check-fast   # 格式、型別、lint 與介面
just check        # 完整 flake checks
just build        # 建置部署產物，不啟用
```

首次啟用前先讀[部署指南](docs/deployment.md)。

```bash
just arch-workstation           # 收斂 Arch 狀態並啟用 Home Manager
just arch-workstation update    # 同時更新宣告的 pacman / AUR 套件
just arch-workstation verbose   # 輸出 Nix、Home Manager 與轉接器診斷
just arch-workstation purge     # 移除受管理的 Arch 部署狀態，略過 Home Manager
```

缺少宣告的原生套件時，日常部署會以代碼 3 停止，改用 `update` 安裝。Arch 變更與 Home Manager 啟用不共用回滾。`just --list` 列出所有指令。

## 設定

[configuration.nix](configuration.nix) 是唯一入口：`hosts/` 以 `lib.mkDefault` 提供預設，這裡的一般定義會覆寫它們。

```nix
networking.hotspot.enable = false;
users.users.abnertu.home.programs.git.settings.init.defaultBranch = "main";
```

查詢解析後的值（不會啟用）：

```bash
nix eval .#lib.configurations.arch.networking.hostname.name
```

Hyprland 與 Neovim 設定來自固定版本的 flake input；要使用本機 worktree，設定 `users.users.<name>.development.hyprlandPath` 與 `neovimPath`。完整選項見[設定指南](docs/configuration.md)。

## 文件

| 指南 | 內容 |
| --- | --- |
| [部署](docs/deployment.md) | bootstrap、啟用、更新、purge 與復原 |
| [設定](docs/configuration.md) | 選項、優先順序與解析結果 |
| [系統設定](docs/system-settings.md) | 原生檔案所有權、預檢與 pending 標記 |
| [桌面工作階段](docs/desktop-session.md) | UWSM、啟動順序與 Noctalia 儲存 |
| [Noctalia 設定](docs/noctalia-config.md) | 擷取並部署審閱過的 UI 偏好 |
| [熱點](docs/hotspot.md) | 接管既有的 NetworkManager AP |
| [本機 AI](docs/ai.md) | 準備模型、loopback 服務與 agent skills；量測結果見 [ai-benchmarks](docs/ai-benchmarks.md) |
| [GitLab Runner](docs/runners.md) | 獨立的 reconcile、註冊與驗證流程 |
| [Personal Agent](docs/personal-agent.md) | 外部執行設定與原生服務 |

架構與組合模型見 [CONTEXT.md](CONTEXT.md)。

## 開發

修改前先讀 [AGENTS.md](AGENTS.md)。組合邏輯或轉接器變更後，在專案根目錄執行：

```bash
just check-fast && just check && just build
nix build --no-link '.#homeConfigurations."abnertu@arch".activationPackage'
```

檢查只使用暫存目錄、假的原生指令與隔離 VM，不會部署或讀取受保護的資料。部署流程或轉接器有變更時，再用 `just container-test` 在 podman 容器裡實際部署一次（見[容器測試](docs/deployment.md#容器測試)）。

CI（GitHub Actions）：

- 每次 push 與 PR：`nix flake check` 與部署建置
- 部署相關變更、每週排程：容器部署測試
- 每週：自動開 PR 更新 flake inputs；Dependabot 更新 workflow actions
