# 共用任務進度

讓工作站的 Bash 與 Python 工具共用同一個 Rich 進度顯示：進行中的任務在同一行更新，結束後的結果與耗時留在 scrollback。任務執行、子行程 I/O、錯誤與復原由呼叫端負責，這個模組只負責顯示。Python 實作在 `nix-adapter`，這裡提供 Bash 端的接法。

## 試用（不改動系統）

在 repo 根目錄進入 `nix develop`，執行這個合成範例：

```bash
python - <<'PY'
import subprocess
import sys
import time
from nix_adapter import Progress

with Progress("Example") as progress:
    with progress.task("Check sample inputs", total=3) as task:
        for completed in range(1, 4):
            time.sleep(0.2)
            task.update(completed)
    with progress.task("Run a sample child") as task:
        with task.external_output():
            subprocess.run(
                [sys.executable, "-c", "print('Original child output')"],
                check=True,
            )
PY
```

執行後會留下兩筆完成紀錄與子行程的原始輸出。沒有總數的工作顯示 spinner；數字代表實際完成量，不是時間估計。任務標籤用固定且不含敏感資訊的文字，不要放指令參數、環境變數、憑證或註冊資料。

## Python 介面

從 `nix_adapter` 匯入 `Progress`。`Progress` context 結束時關閉顯示；`task` context 記錄成功或失敗，但不吞掉例外。`task.update(completed, total=...)` 回報實際進度，`task.finish("skip")` 記錄明確的略過。循序與巢狀任務共用同一個顯示。

子行程或本地 print 要直接寫到終端機前，先進入 `task.external_output()`：它會清除並暫停進度列，寫入結束後再恢復。原本就擷取或隱藏的子行程輸出要維持原樣；有進度顯示不代表敏感輸出可以寫進 log。

## Bash 與 Nix 組合

以 `{ inherit pkgs adapterPython; }` 匯入 [default.nix](default.nix)，它提供 renderer 套件（`renderer`）與 Bash 前導程式碼（`shell`）。在 `writeShellApplication` 裡把 `shell` 接在應用程式的 Bash 原始碼之前。

```bash
progress_init "Example" 0  # 第二個參數是 verbose（0 或 1）
trap 'status=$?; progress_exit "$status"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
progress_start "Check sample inputs" 3
for completed in 1 2 3; do
  sleep 0.2
  progress_update "$completed"
done
progress_finish 'done'
```

- `progress_suspend` / `progress_resume` 把終端機交給外部寫入者；suspend 會等 renderer 確認交接後才返回。
- `progress_finish` 接受 `done`、`skip` 或 `failed`。
- `progress_exit` 接收保存的結束代碼並關閉 renderer；已有 cleanup 的應用程式要在自己的 cleanup 裡呼叫它。模組不取代應用程式的 trap。
- `exec` 交棒前呼叫 `progress_close`，由新行程回報自己的結果。

Bash 端使用專用的控制通道，不讀應用程式的 stdin、不導向子行程輸出，也不傳指令給 renderer。顯示失敗不能取代應用程式的結果或抹掉診斷。

## 終端機行為與測試

進度寫到 stderr。非終端機輸出、verbose、`TERM=dumb`、設定了 `NO_COLOR` 或非空的 `CI` 時，改用純文字的狀態紀錄。顯示暫停期間，原生工具保留自己的輸出。使用一般的 scrollback，不切換到備用畫面。

renderer 與橋接的隔離測試在 `nix-adapter`：

```bash
nix flake check github:gin31259461/nix-adapter
```

工作站指令如何顯示進度，見[部署指南](../../../docs/deployment.md#進度與診斷)。
