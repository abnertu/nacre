# 系統設定

`configuration.nix` 選擇要管理的原生系統功能。`platforms/arch/system/` 負責語系、時區、防火牆等設定，`platforms/arch/core/` 負責其餘的核心檔案、unit、群組與核心參數。每個轉接器只讀一份由 Nix 產生的 manifest，所以收斂與 purge 涵蓋相同的宣告。轉接器在寫入或啟動任何東西之前，會先檢查實際的檔案、所有權、原生指令與 unit。這些 `/etc` 檔案不屬於 Home Manager。

| 選項 | 管理內容 |
| --- | --- |
| `i18n`、`time`、`console` | 語系、時區、鍵盤配置與字型 |
| `networking.hostname`、`networking.firewall`、`networking.hotspot` | 主機名稱、UFW、既有的 NetworkManager AP |
| `services.timesyncd`、`services.journald`、`services.logind`、`services.fstrim`、`services.powerpanel` | systemd 原生設定、UPS daemon 設定與服務狀態 |

系統預檢屬於核心階段：宣告的熱點介面不存在、資源缺漏、與其他提供者或擁有者衝突、指令失敗，都會中止部署，不會被當成可選模組略過。第一次啟用某項功能前，先在能自行復原的本機工作階段確認現有的擁有者，特別是時間同步、儲存裝置 discard、console 資源、NetworkManager 與 UFW。防火牆可以這樣查：

```bash
sudo ufw status verbose
```

接管 AP 見[熱點](hotspot.md)。停用宣告只是不再管理，不會移除既有的檔案、帳號、套件或服務狀態。`purge` 只移除這個轉接器擁有的 drop-in，語系、時區、主機名稱、console、防火牆規則與熱點設定保留現值。

## PowerPanel（CyberPower UPS）

`services.powerpanel` 透過 `/etc/pwrstatd.conf`、AUR 套件 `powerpanel` 與 `pwrstatd.service` 管理 UPS：

- 停電時依剩餘時間關機（`powerfailShutdown = false`、`runtimeThreshold = 300`、`lowbattShutdown = true`），不會一停電就關機。
- 部署使用者會加入 `power` 群組，不需 root 即可執行 `pwrstat -status` 與 `pwrstat -config`。
- `/etc/pwrstatd.conf` 變更時記錄 pending 標記，並自動重啟執行中的 `pwrstatd.service`。

## 變更與復原

轉接器比對檔案內容、所有權與權限，只在真的不同時以原子方式取代。變更前於 `/var/lib/nix-config/arch/` 記錄 pending 標記，對應動作成功後才清除。健康的重跑不會改寫相同的檔案，也不會重啟正常的服務。logind 的變更等到下次開機才生效，不會重啟登入中的工作階段。TRIM timer 保留原生排程並關閉補跑；與其他排程衝突時需要人工確認。

失敗時修正回報的原因，保留標記重跑。`just arch-workstation verbose` 會顯示原生指令與診斷，失敗時保留 stdout、stderr 與逾時前的部分輸出。回報問題時不要附上憑證或無關的應用資料。

只驗證原始碼：

```bash
nix build --no-link --show-trace --print-build-logs \
  .#checks.x86_64-linux.system-settings-interface \
  .#checks.x86_64-linux.system-settings-tests \
  .#checks.x86_64-linux.core-tests \
  .#checks.x86_64-linux.arch-switch-tests \
  .#checks.x86_64-linux.system-firewall-integration
```

這些檢查使用暫存目錄、假的原生指令與隔離 VM。完整驗證用 `just check`。
