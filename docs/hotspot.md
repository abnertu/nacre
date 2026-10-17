# Wi-Fi 熱點

系統轉接器以唯一的連線名稱選定一個既有的 NetworkManager AP 連線，只管理它的公開屬性。UUID、WPA 憑證與其他欄位仍由 NetworkManager 保管，轉接器不會讀取或印出密碼。

## 準備連線

啟用 `networking.hotspot` 前：

1. 確認 NetworkManager 已安裝並在執行。
2. 用 `nmcli` 建立該名稱的 AP 連線，在 NetworkManager 的受保護儲存中設定 WPA personal 與密碼。
3. 確認宣告的無線與上行介面都存在，且無線介面沒有被其他連線占用。

憑證不要放進 Nix、Git、指令參數或 log。

選項寫在 `configuration.nix`，可用[設定](configuration.md)裡的方式查詢解析結果。硬體不同的機器，覆寫 `networking.hotspot.interface` 與 `networking.hotspot.uplink`，或停用這項功能。任一宣告的介面不存在時，核心預檢會在任何變更前失敗；名稱重複、不是 AP 連線、所有權不安全或衝突、原生查詢失敗也一樣。

## 部署與驗證

```bash
just arch-workstation
nmcli -f DEVICE,TYPE,STATE device status
sudo ufw status verbose
```

缺少宣告的原生套件時，確認後改用 `just arch-workstation update`。修改 AP 屬性可能重新啟用連線，讓用戶端短暫斷線；沒有變更的健康連線會持續運作。啟用防火牆管理時，轉接器會為選定的子網段與上行介面產生 IPv4 DHCP、閘道 DNS 與轉送規則；NAT 由 NetworkManager 負責，其餘流量維持預設拒絕。

用一台用戶端確認位址分配、DNS 與上網路由。檢查無線電狀態用 `iw dev <宣告的無線介面> info`。

## 復原

中斷的原生動作會在 `/var/lib/nix-config/arch/` 保留 pending 標記。修正回報的衝突或缺少的前提後重跑部署，不要為了讓重跑通過而刪除標記。停用熱點管理時，既有的 NetworkManager 連線、憑證與執行狀態都會保留。若宣告改了介面、子網段或上行介面，過時的手動規則要自行確認，部署不會推斷你要移除它們。
