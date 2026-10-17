# 設定

在 `configuration.nix` 覆寫選定的 Host。它匯入的 `hosts/arch` 以 `lib.mkDefault` 提供預設值，`configuration.nix` 裡的一般定義優先；匯入順序不影響優先權。未知選項、錯誤型別與無效組合在評估時就會失敗。

```nix
{ ... }:
{
  imports = [ ./hosts/arch ];
  networking.firewall.enable = false;
  services.fstrim.enable = false;
  time.timeZone = "UTC";
}
```

建置或啟用前，查詢解析後的值：

```bash
nix eval .#lib.configurations.arch.networking.hostname.name
nix eval .#lib.configurations.arch.services.fstrim.enable
nix eval --json .#lib.configurations.arch.networking.firewall
```

選項型別由 `lib/configuration-options.nix` 與 `modules/` 下的功能模組定義，跨欄位規則在 `lib/configuration-assertions.nix`，`lib/eval-configuration.nix` 產生內部使用的 Host 與轉接器資料。`hosts/arch` 擁有機器預設與使用者身分；`profiles/`、`homes/` 與 home 模組負責 Home Manager 組合。

## 該改哪裡

| 變更 | 命名空間 |
| --- | --- |
| 網路、熱點、防火牆、主機名稱 | `networking` |
| 語系、時區、console | `i18n`、`time`、`console` |
| 原生服務、AI、Runner、Personal Agent | `services`、`programs.ai` |
| 硬體與虛擬化 | `hardware`、`virtualization` |
| 核心模組與參數 | `boot.kernelModules`、`boot.kernel.sysctl` |
| 圖形工作階段與使用者程式 | `desktop`、`programs`、`users.users.<name>.home` |

上層開關控制它擁有的資源。停用一項 Arch 功能只是不再管理它，不會移除套件、停用服務、刪除註冊或清除應用資料；Home Manager 照常切換到新的世代。

`boot.kernelModules` 與 `boot.kernel.sysctl` 預設為容器網路基準（bridge 模組、轉送、BBR）。可依鍵覆寫單一參數，設為 `null` 撤回，或用 `lib.mkForce` 取代整個模組清單。

AI 模型在 `programs.ai.llama.models.<inventory-key>` 選取：`model.name` 是預設模型，`concurrentModels` 與 `maxLoadedModels` 控制同時常駐的數量。模型設定執行參數，profile 設定取樣與 thinking。`memoryBudgetMiB` 只檢查各模型 `vramEstimateMiB` 的總和，不限制實際配置。修改模型、offload 或 context 前先讀 [AI 指南](ai.md)。AI、Codex 與 llama.cpp 都啟用時，`programs.ai.codex.localProfile.enable`（預設 `true`）管理 `codex --profile llama-cpp` 使用的 `~/.codex/llama-cpp.config.toml`。

## 使用者與 home

預設 Host 以 `deployment.username` 選擇既有的登入帳號，帳號必須在部署前就存在。換成其他使用者時，在 `configuration.nix` 同時修改選定的帳號與宣告的身分，以 [Host users](../hosts/arch/users.nix) 為基準調整。共用的 home 行為放 `profiles/` 或 home 模組，機器差異放 `homes/` 或 Host。服務帳號由各自的模組擁有，不套用 home 設定。例行更新不要調高 Home Manager 的 `stateVersion`。

修改後執行 `just check-fast`、`just check` 與 `just build`。啟用前讀[部署](deployment.md)，變更原生所有權前讀[系統設定](system-settings.md)。
