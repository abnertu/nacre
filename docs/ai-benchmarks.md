# 本機 AI 量測結果

2026-10-06（Asia/Taipei）以合成 prompt 與驗證過的 GGUF 量測。這些結果用來決定 Arch host 的預設值，不是通用的效能保證。

## 環境與方法

| 項目 | 規格 |
| --- | --- |
| GPU | AMD RX 9060 XT（gfx1200），16,304 MiB 獨立 VRAM，計數取自 `/sys/class/drm/card1/device` |
| CPU / RAM | Ryzen 7 7700（8 核 16 緒），約 32 GB |
| 軟體 | 核心 `7.2.6-arch2-1`、Mesa/Vulkan Radeon `26.2.3-1`、ROCm `7.2.4-1` |
| llama.cpp | build 10884，commit `434ddbbc0e30522e897670681e503b797c12b7c1`，grammar 上限 20,000 |
| 路由 | llama-swap 224，使用 Nix 產生的設定，只改模型路徑與 loopback 測試埠 |

`llama-bench` 量測 PP512、PP4096、TG128，通常各三次。比較了 ROCm0 / Vulkan0、q8 / q4 KV、ubatch 64 / 256 / 512 / 1024、batch 1024 / 2048，以及適用時的 threads 4 / 8。最終設定：Vulkan0、全部 GPU layer、flash attention 開、q8 KV、batch 2048、ubatch 512、8 threads。ubatch 提高到 1024 時，4B 的 PP4096 從 3,277 降到 2,979 tok/s，峰值 VRAM 多約 508 MiB。

## 候選模型

| 模型 | PP512 tok/s | PP4096 tok/s | TG128 tok/s | GPU 峰值 MiB |
| --- | ---: | ---: | ---: | ---: |
| 原有 Qwen3.6 35B A3B MXFP4，ROCm，16 GPU layers | 486 | — | 20.8 | 9,940 |
| Qwen3.5 9B Q4_K_M，Vulkan | 1,923 | 2,054 | 49.3 | 約 6,667 |
| Qwen3.5 4B Q4_K_M，Vulkan | 2,568 | 3,274 | 80.3 | 4,401 |
| Qwen2.5 Coder 1.5B Q8_0，Vulkan | 6,069 | 9,039 | 145.8 | 3,090 |
| Qwen2.5 Coder 3B Q4_K_M，Vulkan | 3,295 | 4,804 | 118.4 | 3,382 |

原基準只重複兩次。1.5B 與最初的 9B 使用 flash attention auto；明確開啟的 9B 對照同樣低於 50。峰值包含桌面本身的用量，是取樣值而非配置上限。模型身分與 checksum 鎖在[資源清單](../modules/ai/artifacts.nix)。

- **預設 agent 選 4B**：9B 沒達到速度目標。
- **補全選 3B**：在 Python、JavaScript、Nix 的四個小型語法與結果測試中全部通過，1.5B 通過三個。這組測試太小，不代表一般程式能力，也不代表與原本的 35B 相當。
- FIM 的 prefix 要帶語言提示：沒有 `# Nix expression` 註解時，兩個模型都認錯了 Nix 片段。

## 路由與 context

兩個模型同時常駐時：

| 情境 | agent 生成 | 補全生成 | 首個內容（warm） | GPU 峰值 |
| --- | --- | --- | --- | --- |
| 9,518 token prompt | 單獨 74.8 tok/s；並行 67.1–67.3 tok/s | 61.0–62.2 tok/s | agent 48–50 ms、補全 10–35 ms | 6,536 MiB |
| 接近舊的 32K 上限，重複並行 | 48.0–48.2 tok/s | — | cold 首個內容 13.9 s | — |
| 最終 16K 設定，15,168 token prompt 生成 128 token | 單獨 72.4 tok/s；並行 59.9、50.24、50.23 tok/s | 84.3、60.8、60.9 tok/s | agent 50–55 ms（cold 6.71 s） | 6,263 MiB |

第一列的 cold agent 請求在出現內容前花了 3.21 秒，可看出 prompt 處理與生成速度的差別。因為接近 32K 時速度明顯下降，預設 agent context 定為 16K，補全為 4K；更大的 context 仍可設定，但有實測的速度代價。工具應壓縮累積的歷史並為輸出保留空間；工具本身的執行與網路延遲不在模型速度內，這次也沒有外部工具可做端對端量測。最終設定在這些樣本中都超過 50 tok/s，但長 context 時餘裕很小，不保證所有工作負載。

宣告的估計值是 agent 6,144 MiB、補全 3,072 MiB，合計在 11,264 MiB 預算內。這只是驗證宣告值，不是 GPU 配置的硬上限。量測工具在獨立 VRAM 可用量低於 4,096 MiB 時停止自己的子行程。這次無法實測 Sunshine 串流；記憶體餘裕不能證明不會掉幀或斷線。

## Thinking 與診斷

- 原本的 Qwen3.6 以 `enable_thinking=false` 與 `true` 測試：false 對 `17 * 23` 直接回 `391`；true 產生推理，在 256 token 上限內沒輸出最終答案。檢查範本確認是封閉的空 thinking 區塊與開啟的區塊之別。兩者解碼都約 21 tok/s：關閉 thinking 減少生成量，但沒解決解碼慢的問題。
- 選定的 4B 透過路由別名測試：false 不推理直接回 `391`；thinking 別名在足夠的輸出上限下推理後回 `391`。重複請求確認 prompt cache 會被重用。合成的 tool call 請求產生預期的 `lookup_symbol` 呼叫與參數。
- 原模型受記憶體限制只部分 offload 到 GPU。改善來自完全 offload 的小模型、這張卡上的 Vulkan、flash attention 與較短的 context。平行 slot 共用運算與 KV 記憶體，不保證單一請求變快；目前每個後端一個 slot，讓兩個模型能同時工作。
- 原 GGUF 沒有 MTP/nextn tensor，無法只靠加參數啟用 MTP，draft tensor 與緩衝也會占記憶體；達到目標不需要 MTP。

參考來源：[Unsloth Qwen3.6](https://unsloth.ai/docs/models/qwen3.6)、[Qwen3.5 4B model card](https://huggingface.co/Qwen/Qwen3.5-4B)、[Qwen2.5 Coder 1.5B model card](https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B)、[llama.cpp HIP prompt 處理討論](https://github.com/ggml-org/llama.cpp/issues/18823)、[MTP 緩衝討論](https://github.com/ggml-org/llama.cpp/issues/26038)。這些 issue 是排查線索，不代表這台機器遇到同樣的 bug。

設定、重現指令與部署見 [AI 指南](ai.md)。量測的暫存資料在 store 之外的 `/var/tmp/nix-ai-benchmark`，不會自動清除。
