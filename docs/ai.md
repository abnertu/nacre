# 本機 AI 服務

AI 功能以鎖定版本的原生 llama.cpp 執行宣告的 GGUF 模型，前面由 llama-swap 路由。Nix 產生路由、Caddy 與 systemd 設定；Arch 轉接器在套用前檢查已準備的資源、所有權與服務狀態。編譯出的執行檔與模型放在宣告的原生路徑，不在 Nix store。

```text
Tailnet HTTPS → Tailscale Serve → loopback Caddy → loopback llama-swap → loopback llama-server
```

Caddy 只轉送 `/health` 與 `/v1/*`，不公開管理端點。模型、profile、版本與 checksum 清單在 AI 模組的 Nix 宣告裡。

## 選擇常駐模型

`programs.ai.llama.model.name` 是預設模型。`llama.models` 為空時維持舊的單一模型行為；有明確項目時，每個要用的模型（包含 `model.name`）都要啟用：

```nix
programs.ai.llama = {
  model.name = "qwen3.5-4b-q4-k-m";
  concurrentModels = true;
  maxLoadedModels = 2;
  memoryBudgetMiB = 11264;
  models = {
    "qwen3.5-4b-q4-k-m" = {
      enable = true;
      contextSize = 16384;
      fit = false;
      gpuLayers = 99;
      vramEstimateMiB = 6144;
    };
    "qwen2.5-coder-3b-q4-k-m" = {
      enable = true;
      contextSize = 4096;
      vramEstimateMiB = 3072;
    };
  };
};
```

- 每個模型各自設定裝置、context、cache、batch、平行 slot 與 offload；預設模型先套用舊的 `llama.model` 覆寫，再套用個別設定。
- profile 共用模型行程，只控制取樣與 thinking，不能改變後端配置。
- 未知欄位、指向未選模型的 profile、無效的 batch 與衝突的 thinking 設定，在評估時就會失敗。
- 啟用並行時，選取的數量不能超過 `maxLoadedModels`。後端在第一次請求時載入，之後常駐不回收，請求可同時執行；只調高上限不會啟動模型。停用並行時上限必須是 1，模型依需求切換。
- 準備只涵蓋選取的模型；取消選取不會刪除資源。

`vramEstimateMiB` 與 `memoryBudgetMiB` 描述實測的運作預算：設定預算時每個選取的模型都要有估計值，總和不能超過預算。它們不限制實際配置。`--fit-target` 是保留的可用記憶體，不是配置上限。用固定的 offload、context 與 batch 搭配 `fit = false`，可避免結果依載入順序而變。量測 prompt 處理的峰值，為桌面與 Sunshine 保留餘裕，換模型或執行環境後重新量測。

`qwen3.6-35b-a3b-ud-q5-k-m` 這個選項名稱為了相容而保留，實際檔案是 MXFP4_MOE。thinking profile 的後綴仍可用於預設模型；確切的 API ID 查 `/v1/models`。

## Agent skills

Home Manager 把明確選取的 skill 以完整目錄連結安裝到 `~/.agents/skills` 與 `~/.gemini/config/skills`：

- 共用的 agent 目錄由 `programs.ai.enable` 與 `programs.ai.skillsPresets.enable` 控制。
- Antigravity 目錄由 `programs.ai.agy.enable` 與 `programs.ai.agy.skills.enable` 控制。
- 這些開關與 llama.cpp 資源的準備無關。

來源與選取清單在 [`modules/ai/skills.nix`](../modules/ai/skills.nix)。`matt-pocock-skills` input 提供 Matt 的 skill（含參考資料、腳本與 metadata），`vercel-skills` input 提供 `find-skills`，兩者的版本都鎖在 `flake.lock`；自訂 skill 留在這個 repo。部署使用 Home Manager 啟用套件裡已建置好的來源，不會執行 `npx`、不在啟用時下載，也不維護 Skills CLI 的 lock 檔。

只更新 skill 來源、審閱上游變更後驗證：

```bash
nix flake update matt-pocock-skills vercel-skills
just check
just build
```

兩個 input 可以分開更新。確認無誤後執行 `just arch-workstation` 啟用並 commit lock 變更；要還原就把 lock 改回先前的版本再重新部署。`just arch-workstation update` 只負責原生套件，不會推進 skill 版本。

新增 skill 需要修改選取清單。選取的上游路徑消失或缺少 `SKILL.md` 時評估會失敗，所以更新不會悄悄漏掉 skill。不要用 `npx skills update` 覆寫這些由 Home Manager 管理的連結；要修改上游 skill，先另外 fork 成自訂 skill。需要專案層級的設定時，在各專案另外執行 `setup-matt-pocock-skills`。Antigravity 的全域 skill 路徑見其[官方說明](https://antigravity.google/docs/skills)。

## Codex 本機 profile

AI、Codex 與 llama.cpp 都啟用時，Home Manager 依預設模型的 API ID 與 context 產生 `~/.codex/llama-cpp.config.toml`：

- provider 為 `llama_cpp`（Responses API，`http://127.0.0.1:11434/v1`），這個 profile 關閉網頁搜尋。
- 在 context 的 75% 自動壓縮；預設 16K 時於 12K token 壓縮，留約 4K 給當前回合。這是壓縮門檻，不是輸出上限。
- 關閉 Codex 的 multi-agent 工具，因為鎖定版本的 llama.cpp Responses 轉換只支援 function tool；一般的 function tool 與 shell 仍可用，其他 profile 不受影響。

用 `codex --profile llama-cpp` 或 `codex exec --profile llama-cpp "任務"` 選用（需要 [Codex 0.134 以上](https://learn.chatgpt.com/docs/config-file/config-advanced)）。使用前先準備 AI 資源並收斂服務。換模型或 context 後，下一個 Home Manager 世代啟用時生效。

Qwen3.5 使用受管理的 chat template，依對話順序保留多個 system/developer 指令（包含使用者訊息後的指令更新），原本的 tool 與 thinking 格式不變。GGUF 內建的範本會以 HTTP 500（`System message must be at the beginning`）拒絕這些指令，Codex 可能顯示成一般的高負載錯誤。範本更新後重新部署即可，不需重新下載或建置模型。

`--profile` 讀的是預設 `~/.codex` 下的檔案；自訂 `CODEX_HOME` 時不會讀到。`programs.ai.codex.localProfile.enable = false` 可停止管理。這個檔案獨立於 `~/.codex/config.toml`，模組不管理 Codex 的其他設定、憑證或權限；啟用前先處理既有的同名檔案。

## FIM 補全

透過 `/v1/completions` 使用 base completion 權重，以原始的 prefix/suffix token 而非 chat 訊息：

```bash
curl --fail http://127.0.0.1:11434/v1/completions \
  -H 'Content-Type: application/json' \
  --data '{"model":"Qwen2.5-Coder-3B-Q4_K_M.gguf","prompt":"<|fim_prefix|>def add(a, b):\n    <|fim_suffix|>\n\nassert add(2, 3) == 5\n<|fim_middle|>","max_tokens":64,"temperature":0,"stop":["<|fim_pad|>","<|endoftext|>","<|im_end|>"]}'
```

兩個補全候選模型都有這些 FIM token；因為它們的 GGUF EOS 宣告不同，所以明確設定 stop。內建的 chat 範本不會讓 base 權重變成 instruct 模型。編輯器外掛用另一個補全 ID 與 prefix/suffix 格式；語法不明確時，在 prefix 加上檔案或語言提示（例如 `# Nix expression`）。預設模型總 context 為 16K，讓工具在 prompt 加輸出達到上限前壓縮；加大 context 要重新量測速度。

## 本機量測

這些工具會實際使用 GPU，與部署和 flake checks 分開。候選模型下載到暫存目錄並驗證 SHA-256。避免在受管理的路由之外再跑一個大型模型；需要隔離測試時，在約定的時間停止路由，結束後恢復，不要修改 `/etc`、收據或已準備的 selector。

先找出獨立顯示卡的 sysfs 路徑，不要假設是 `card0`：

```bash
for device in /sys/class/drm/card[0-9]/device; do
  test ! -f "$device/mem_info_vram_total" || {
    printf '%s\n' "$device"
    cat "$device/mem_info_vram_total" "$device/mem_info_vram_used"
  }
done
python modules/ai/benchmark.py \
  --model /path/to/verified-model.gguf \
  --binary-prefix /opt/llama-cpp-opencode/current \
  --device-path /sys/class/drm/card1/device \
  --devices ROCm0,Vulkan0 --batches 2048 --ubatches 64,512 \
  --caches q8_0,q4_0 --threads 8 --gpu-layers 99 \
  --min-free-mib 4096 --output /var/tmp/ai-bench.json
```

依序量測 PP512、PP4096、TG128，各重複三次，記錄執行檔版本、模型 checksum、參數、原始診斷與 VRAM 峰值。`--depths 8192` 可量測較長前綴後的生成速度。保留量監控在超出或逾時時終止自己的測試行程；輪詢擋不住瞬間配置，不是硬上限。

```bash
python modules/ai/probe.py --base-url http://127.0.0.1:11434 \
  --model MODEL_ID --thinking-model MODEL_ID:thinking-coding \
  --output /var/tmp/ai-chat.json
python modules/ai/probe.py --base-url http://127.0.0.1:11434 \
  --model COMPLETION_ID --mode fim --output /var/tmp/ai-fim.json
```

probe 使用合成的 prompt，比較 thinking 開關，並重複前綴以觀察 cache 重用。它分開記錄第一個 SSE 事件、推理與可見回答，失敗與部分輸出也會保留。路由的別名可能強制 thinking 設定，用 `--thinking-model` 與預設模型比較；token 上限可能在最終回答前就結束 thinking。不要用空 context 的 TG128 推論長 context 的速度。

agent 延遲包含載入、排隊、prompt 處理、推理與可見輸出；穩定的前綴有助 cache 重用。MTP 能加速解碼，但需要 MTP tensor 並增加記憶體，目前鎖定的 Qwen3.6 MXFP4 檔案沒有；只有解碼是瓶頸且預算允許時才測。上游的 [HIP PP 退化 #18823](https://github.com/ggml-org/llama.cpp/issues/18823) 與 [MTP 預留 #26038](https://github.com/ggml-org/llama.cpp/issues/26038) 只是排查線索，不代表這台機器有這些問題。

硬體、選定參數與限制見[本機量測結果](ai-benchmarks.md)。宣稱遠端串流效能前，要在實際 Sunshine 串流時測試同時常駐與並行請求。

## 準備（部署之外）

```bash
just prepare-ai          # 建置並驗證所有宣告的資源
just prepare-ai build    # 只準備鎖定版本的 llama.cpp
just prepare-ai model    # 只下載並完整驗證宣告的模型
```

- 建置使用宣告的 llama.cpp 版本與審閱過的 patch，安裝到以版本命名的目錄，再以原子方式更新 `current` selector。需要原生的 C++、ROCm 與 Vulkan 工具鏈。
- 模型依宣告的身分暫存，通過完整 SHA-256 驗證後才以原子方式發布，並寫入 root 擁有的收據。日常部署只比對收據的身分與檔案 metadata，不會每次雜湊整個 GGUF；`just prepare-ai model` 會完整驗證並更新相符的收據。
- 未知的暫存狀態、不符的 selector 或 checksum 需要人工確認。
- 下載使用 `hf download --local-dir`，不用 `--cache-dir`，metadata 留在自己的暫存目錄。下載失敗時重跑 `just prepare-ai model`：相同身分的暫存會被沿用，完成後仍須通過 SHA-256 驗證；屬於其他宣告的暫存仍需人工確認。見 [Hugging Face 下載說明](https://huggingface.co/docs/huggingface_hub/guides/download)。

## 部署與檢查

```bash
just arch-workstation
curl --fail http://127.0.0.1:11434/v1/models
curl --fail http://127.0.0.1:11435/v1/models
sudo tailscale serve status --json
systemctl status llama-swap.service caddy.service
```

從未準備過 build selector 時，部署會醒目地略過 AI，不碰它的檔案與服務。selector 存在之後，缺模型、build 或模型收據無效、checksum 改變、Caddy 設定不受管理、服務失敗，或預檢後狀態改變，都會中止部署。服務收斂前會先驗證已準備的資源。需要原生指令的診斷時用 `just arch-workstation verbose`。

舊的獨立 `llama-server` preset 與 drop-in 以固定的歷史內容辨識，與目前選取的模型無關。內容完全相符的舊檔在遷移到 llama-swap 期間可以保留，部署會在需要時停用舊服務；被修改過的 preset、drop-in 與手動覆寫仍需明確接管。舊檔與模型資源不會被自動移除。

停用 AI 只是停止收斂，不會移除已準備的執行檔、模型、原生檔案、pending 標記或 Tailscale 路由。`purge` 會撤下 Tailscale Serve 路由、Caddy site 與 `llama-swap`，保留已準備的執行檔、模型與收據。進度與復原見[部署](deployment.md)。
