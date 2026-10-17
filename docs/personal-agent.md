# Personal Agent

`services.personalAgent.enable` 啟用鎖定版本的 `personal-agent` flake 套件。應用程式的 Python 依賴與內部行為由它自己的 repo 負責；這個 repo 負責 Arch 帳號、原生目錄、unit 與服務收斂。unit 由 Nix 產生，執行設定與資料庫不放進 Git 或 Nix store。

設定檔由你在 repo 之外提供：

| 路徑 | 內容 | 擁有者與權限 |
| --- | --- | --- |
| `/etc/personal-agent/config.toml` | 應用身分與推論設定 | `root:personal-agent`，`0640` |
| `/etc/personal-agent/agent.env` | 機密 token | `root:root`，`0600` |
| `/var/lib/personal-agent/` | 資料庫 | — |

部署只檢查這些路徑存在與 metadata 是否正確，不會印出內容。不要把它們的內容放進診斷資訊。

從未設定過時，模組可以回報 `not ready` 並被略過。設定過之後，設定缺失或不安全就是執行狀態漂移，會中止部署；預檢後狀態才改變的情況也會中止，不會變成略過。更新應用程式就是刻意更新 flake input，再跑檢查與建置：

```bash
nix flake update personal-agent
just check
just build
```

## 操作服務

```bash
sudo systemctl status personal-agent.service
sudo journalctl -u personal-agent.service -f
```

停用宣告只是不再管理，不會刪除帳號、設定或資料庫。工作站的 purge 會移除受管理的 unit 並停止服務，同樣保留這些資料與帳號，範圍與復原方式見[部署](deployment.md)。
