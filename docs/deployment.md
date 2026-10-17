# 部署與復原

以選定的部署使用者，在 `x86_64-linux` 的 Arch 上從這個 checkout 執行。前提：

- 帳號已存在且屬於 `wheel`
- 已安裝原生 Nix、`yay` 與必要指令
- 宣告了 `lib32-*` 套件時，`/etc/pacman.conf` 已啟用 `[multilib]`
- 執行中的核心有對應的模組目錄

啟用前先讀[設定](configuration.md)、[系統設定](system-settings.md)，以及已啟用功能的準備指南。

## Bootstrap

全新的 Arch 尚未安裝 Nix 或 just 時，clone 後執行 bootstrap。它會啟用 `[multilib]`、安裝前置套件、設定 Nix 並啟動 `nix-daemon.service`：

```bash
git clone https://github.com/gin31259461/nix-config.git ~/.config/nix
cd ~/.config/nix
./scripts/bootstrap.sh
```

Bootstrap 會改動主機，執行前先看過腳本與現有套件狀態。

## 容器測試

`just container-test` 用 podman 把 `checks/container/configuration.nix`（工作站設定扣除 rootless 容器無法提供的硬體與核心功能）部署進 systemd Arch 容器，依序驗證：

1. 以 checked-in 的 bootstrap 準備環境
2. 缺套件時以代碼 3 停止
3. `update` 成功
4. 再跑一次沒有任何變更
5. `plan` 也回報沒有變更
6. purge 後 pacman 仍可用
7. store 路徑未被修改

pacman 與 yay 快取存在 `nix-config-container-pacman`、`nix-config-container-yay` 兩個 volume，第一次會下載完整套件。`--keep` 保留容器以便檢查。CI 在 `main` 的部署相關變更、每週排程與手動觸發時執行同一測試（`.github/workflows/container-test.yml`）。

## 檢查與啟用

```bash
just check-fast                 # 格式、型別、lint 與介面
just check                      # 所有 flake checks，含隔離測試
just build                      # 建置部署產物，不啟用
just arch-workstation plan      # 預覽部署會做的變更，不改任何東西
just arch-workstation           # 收斂 Arch，再啟用建置好的 home
just arch-workstation update    # 同時升級並收斂宣告的 pacman / AUR 套件
just arch-workstation verbose   # 輸出完整診斷
just arch-workstation purge     # 移除受管理的 Arch 部署狀態，略過 home
```

- `plan` 只讀：列出缺少與可升級的套件、core 的每一項檔案與 runtime 變更、system 與可選模組的預檢結果，以及 Home Manager 世代是否更新。每行以 `=`（不變）、`~`（變更）、`+`（新增）、`!`（衝突）開頭，終端機上依此上色；有衝突時以非零代碼結束。system settings 目前只顯示預檢結果，不預覽細項。
- 日常部署不安裝套件；缺套件時以代碼 3 停止，改用 `update`。
- `update` 完整升級 pacman 並收斂 AUR；核心更新後可能需要重新開機。
- `purge` 停用受管理的系統 unit，移除目前宣告的核心檔案、LizardByte 套件庫、Personal Agent unit、pending 狀態與 Nix 設定區塊；保留套件、帳號、Runner 註冊與可變資料。已停用功能的檔案不再受管理，purge 不會動；system-settings、AI 與 initramfs 的變更也不會撤回。purge 不啟用 Home Manager。

`just arch-workstation` 先建置內含固定 Home Manager 啟用套件的部署產物，執行時依序：預檢核心狀態與可選模組、（`update` 時）更新套件、收斂原生檔案與服務、啟用 home。兩個階段沒有共同的回滾：home 啟用失敗時，Arch 的變更仍保留。Runner 與 [AI 準備](ai.md) 不在這個流程內。

可選模組只有在從未完成準備時才能回報 `not ready` 並被略過，略過時不碰它的檔案與服務。無效的收據、checksum 不符、所有權衝突、缺少宣告的核心硬體、原生指令失敗，以及預檢後狀態改變，都會中止部署。

## 進度與診斷

Nix 顯示原生建置進度；部署開始後，共用的進度列顯示進行中、完成、略過與失敗的任務，原生工具輸出時會讓出終端機。`verbose`、stderr 被導向、`TERM=dumb`、設定了 `NO_COLOR`（空值也算）或非空的 `CI`，會改用純文字 log。`verbose` 會傳到 Nix、Home Manager 與特權轉接器。轉接器失敗時附上指令、結束代碼、stdout、stderr 與逾時前的部分輸出，機密會遮蔽。

```bash
NO_COLOR=1 just build
just arch-workstation update verbose
```

直接呼叫時，Nix 參數放在目標前，轉接器參數放在 `--` 之後：

```bash
nix run --show-trace --print-build-logs --verbose .#arch-workstation -- --verbose
```

## 中斷後復原

| 狀況 | 處理 |
| --- | --- |
| 代碼 2 | 修正指令參數 |
| 代碼 3 | 確認缺少的原生套件，需要時執行 `update` |
| 代碼 75 | 等待鎖釋放，或開機到模組相符的核心 |
| 可選模組被略過 | 完成該模組的準備步驟 |
| 原生指令失敗 | 修正回報的原因後重跑同一指令 |

受管理的寫入在變更前於 `/var/lib/nix-config/arch/` 記錄 pending 標記，成功後才清除。保留這些標記讓重跑能接續，不要刪除它們來掩蓋未完成的工作。健康的重跑不會改寫相同的檔案，也不會重啟正常的服務。Home Manager 在 Arch 收斂後失敗時，修正 home 的錯誤再重跑部署。purge 不是復原捷徑。
