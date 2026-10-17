# GitLab Runner

每個 Runner instance 是一個以服務環境命名的 TOML 檔：`hosts/arch/runners/frontend.toml` 宣告 `frontend` instance，以 `gitlab-runner-frontend` 帳號執行。共用的 GitLab 與網路設定放在 `common.toml`，instance 檔以 `extends` 引用。`services.gitlabRunner.configFiles` 列出要管理的檔案，增刪檔案即增刪 instance。檔案格式見 [runnerctl README](https://github.com/gin31259461/gitlab-runner#configure)。

每個 instance 擁有專用的服務帳號、子 UID/GID 範圍、rootless Podman、manager 容器、user service 與 GitLab 註冊。`runnerctl` 驗證整組檔案、產生註冊範本、設定與 user unit，並負責帳號與執行環境的收斂、註冊與 token 合併。它不需要 Nix；這個 repo 只鎖定它的版本並傳入檔案。token 不會進入 Git 或 Nix store。

Runner 的操作獨立於 `just arch-workstation`。工作站在 `update` 時會安裝宣告的原生依賴，但不會收斂或註冊 instance。

## 收斂

```bash
just prepare-runner frontend
```

換成要操作的 instance 名稱。收斂會檢查必要的網路介面、專用帳號、子 ID 範圍與 rootless Podman socket，再準備目錄、設定、manager 映像與 user service。遇到衝突時拒絕，不會取代其他擁有者的資源。它不會建立 GitLab 註冊。manager 只能存取自己的 rootless socket；job 以非特權身分在各自的網路中執行，拿不到該 socket。

## 註冊（一次）

在 GitLab 建立 Runner 並取得 authentication token，只透過這次指令的環境變數傳入：

```bash
read -rsp 'GitLab Runner token: ' GITLAB_RUNNER_TOKEN
export GITLAB_RUNNER_TOKEN
just initialize-runner frontend
unset GITLAB_RUNNER_TOKEN
```

註冊前必須先收斂成功；已有不同的註冊時會拒絕。`initialize-runner` 只在註冊時讓 token 通過 sudo，並隱藏含敏感資訊的輸出。token 不要放進設定、derivation、指令參數或 log。

## 驗證、檢查與復原

```bash
just verify-runner frontend
just status-runner frontend
```

驗證會檢查註冊、服務、manager 映像與掛載隔離、socket、GitLab 健康狀態，以及一次性的 job 網路。status 只摘要狀態，不含敏感資訊。所有操作共用 `/run/lock/nix-config-runner.lock`；受管理的寫入拒絕 symlink、hard link 與非預期的檔案類型。收斂或憑證處理被中斷時，instance 設定目錄內會保留私有的 pending 標記；修正原因後重跑，不要以刪除註冊、帳號、子 ID 或標記作為捷徑。從 `configFiles` 移除檔案只是不再管理與安裝依賴，不會刪除執行狀態。

只驗證原始碼：

```bash
just check
nix build --no-link --show-trace --print-build-logs .#runnerctl
```

`just check` 會對宣告的檔案執行 `runnerctl validate`。runnerctl 自己的測試使用隔離的宣告與假操作，不會連到實際的 GitLab Runner。
