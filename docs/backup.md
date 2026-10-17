# 備份清單

這個 repo 可以完整重建工作站；需要備份的是 repo 之外、無法重建或重建代價高的狀態。部署流程不會自動備份（見 AGENTS.md），以下由你手動處理。這些檔案多半含機密，備份媒介要加密，也不要放進 Git。

## 必須備份

遺失後無法還原，或會讓既有資料失效。

| 狀態 | 位置 | 遺失的後果 |
| --- | --- | --- |
| GPG 私鑰 | `~/.gnupg/` | `pass` 與 Git credential（GPG store）全部無法解密 |
| 密碼庫 | `~/.password-store/` | 所有密碼遺失 |
| SSH 金鑰 | `~/.ssh/` | 需要重新產生並到各服務更新公鑰 |
| Noctalia 加密儲存金鑰 | `~/.local/share/noctalia/file-key-v1/master-key` | 部署會產生新金鑰，舊的加密資料無法讀取 |
| Personal Agent 設定與機密 | `/etc/personal-agent/config.toml`、`/etc/personal-agent/agent.env` | 需要重新取得所有 token |
| Personal Agent 資料庫 | `/var/lib/personal-agent/` | 應用資料遺失 |
| 熱點連線（含 WPA 密碼） | `/etc/NetworkManager/system-connections/` | 需要重新建立 AP 連線 |

## 可重建，但備份能省時間

| 狀態 | 位置 | 不備份時的做法 |
| --- | --- | --- |
| Runner 註冊（部署後才有） | `/home/gitlab-runner-<env>/gitlab-runner/config/config.toml` | 在 GitLab 建立新 Runner，重新 `initialize-runner` |
| Tailscale 節點身分 | `/var/lib/tailscale/` | 重新登入，節點會以新身分加入 tailnet |
| AI 執行檔與模型 | llama.cpp 安裝目錄與模型路徑（見 AI 模組宣告） | `just prepare-ai` 重新建置與下載，模型有數 GB |
| 各工具的登入狀態 | 例如 `~/.codex/`、OneDrive 的 refresh token | 重新登入或授權 |

## 不需要備份

- 這個 repo 管理的設定：從 Git 重建。
- Nix store、Home Manager 世代：重新建置。
- `/var/lib/nix-config/arch/` 的 pending 標記：只對中斷中的部署有意義。

## 還原順序

1. 安裝 Arch，建立同名的使用者帳號（`wheel`）。
2. clone 這個 repo 並執行 [bootstrap](deployment.md#bootstrap)。
3. 還原「必須備份」的檔案，保持原本的擁有者與權限（Personal Agent 的權限見 [Personal Agent](personal-agent.md)）。
4. `just arch-workstation plan` 預覽，再 `just arch-workstation update` 部署。
5. 依需要 `just prepare-ai`、重新註冊 Runner。
