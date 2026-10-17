usage() { printf 'usage: llama-prepare [--build-only | --model-only]\n'; }
build=1
model=1
case "${1:-}" in
  '') ;;
  --build-only) model=0 ;;
  --model-only) build=0 ;;
  --help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

prepare_mode="all"
if ((build && !model)); then prepare_mode="build"; elif ((!build && model)); then prepare_mode="model"; fi
progress_init "AI preparation ($prepare_mode)" "${verbose:-0}"
report_error() {
  progress_suspend
  printf '%s\n' "$1" >&2
}
prepare_exit() {
  local status=$?
  progress_exit "$status"
}
trap prepare_exit EXIT
run_with_progress() {
  local status
  progress_suspend
  status=0
  "$@" || status=$?
  progress_resume
  return "$status"
}

((EUID == 0)) || { report_error "run llama-prepare as root (sudo nix --extra-experimental-features 'nix-command flakes' run .#llama-prepare)"; exit 1; }
work=$(mktemp -d /var/tmp/nacre-llama.XXXXXXXX)
chmod 0700 "$work"
prepare_cleanup() {
  local status=$?
  progress_exit "$status"
  rm -rf -- "$work"
  return "$status"
}
trap prepare_cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
exec {lock_fd}>/run/lock/nacre-llama-prepare.lock
flock -n "$lock_fd" || { report_error 'another llama-prepare is running'; exit 75; }
if ((build)); then
  [[ -x /usr/bin/c++ && -x /opt/rocm/bin/hipcc && -f /usr/include/vulkan/vulkan.h ]] || {
    report_error 'native C++, ROCm, or Vulkan development toolchain is missing'; exit 1;
  }
  revision_dir="$install_prefix/revisions/$source_revision-$grammar_threshold"
  receipt="$revision_dir/nix-config-build"
  receipt_text="$source_revision $grammar_threshold"
  cached_build=0
  [[ ! -L $revision_dir ]] || { report_error 'revision path must not be a symlink'; exit 1; }
  if [[ -e $revision_dir ]]; then
    cached_build=1
    progress_start 'Select cached llama.cpp build'
    [[ -f $receipt && $(<"$receipt") == "$receipt_text" && -x $revision_dir/bin/llama-server ]] || {
      report_error 'existing llama.cpp revision directory is not owned by this declaration'
      exit 1
    }
  else
    progress_start 'Build llama.cpp' 5
    run_with_progress git clone --filter=blob:none --no-checkout -- "$source_repository" "$work/llama.cpp"
    progress_update 1 5
    run_with_progress git -C "$work/llama.cpp" checkout --detach "$source_revision"
    grammar="$work/llama.cpp/src/llama-grammar.cpp"
    expected='#define MAX_REPETITION_THRESHOLD 2000'
    [[ $(grep -Fxc "$expected" "$grammar") == 1 ]] || {
      report_error 'pinned source no longer contains the reviewed grammar threshold'
      exit 1
    }
    sed -i "s/$expected/#define MAX_REPETITION_THRESHOLD $grammar_threshold/" "$grammar"
    progress_update 2 5
    run_with_progress cmake -S "$work/llama.cpp" -B "$work/build" -G Ninja \
      -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$work/install" \
      -DVulkan_INCLUDE_DIR=/usr/include -DVulkan_LIBRARY=/usr/lib/libvulkan.so \
      -DGGML_HIP=ON -DGGML_VULKAN=ON -DLLAMA_CURL=ON
    progress_update 3 5
    run_with_progress cmake --build "$work/build" --target install
    stage="$install_prefix/revisions/.nix-config-$source_revision-$grammar_threshold"
    install -d -m0755 -o0 -g0 "$install_prefix/revisions"
    [[ ! -e $stage && ! -L $stage ]] || { report_error 'stale llama.cpp preparation stage requires operator review'; exit 1; }
    progress_update 4 5
    run_with_progress cp -a "$work/install" "$stage"
    chown -R 0:0 "$stage"
    printf '%s\n' "$receipt_text" >"$stage/nix-config-build"
    chmod 0644 "$stage/nix-config-build"
    run_with_progress mv -T "$stage" "$revision_dir"
  fi
  link_stage="$install_prefix/.current-$source_revision-$grammar_threshold"
  desired_link="revisions/$source_revision-$grammar_threshold"
  if [[ -L $install_prefix/current ]]; then
    current_link=$(readlink "$install_prefix/current")
    [[ -d $install_prefix/current ]] || { report_error 'current llama.cpp selector is dangling'; exit 1; }
    [[ $current_link == "$desired_link" ]] ||
      [[ $current_link =~ ^revisions/[0-9a-f]{40}-[0-9]+$ ]] || {
        report_error 'existing current link is not owned by llama-prepare'; exit 1;
      }
  elif [[ -e $install_prefix/current ]]; then
    report_error 'existing current path is not owned by llama-prepare'; exit 1
  fi
  if [[ ${current_link:-} != "$desired_link" ]]; then
    run_with_progress ln -s "$desired_link" "$link_stage"
    run_with_progress mv -Tf "$link_stage" "$install_prefix/current"
  fi
  if ((cached_build)); then
    progress_finish 'done'
  else
    progress_update 5 5
    progress_finish 'done'
  fi
fi
if ((model)); then
  model_total=${#model_paths[@]}
  for model_index in "${!model_paths[@]}"; do
    model_label="model $((model_index + 1)) of $model_total"
    progress_start "Check $model_label"
    model_path=${model_paths[$model_index]}
    model_sha256=${model_sha256s[$model_index]}
    model_file=${model_files[$model_index]}
    model_repository=${model_repositories[$model_index]}
    model_revision=${model_revisions[$model_index]}
    model_receipt="$model_path.nix-config-receipt"
    [[ ! -L $model_path ]] || { report_error 'model path must not be a symlink'; exit 1; }
    current=''
    if [[ -f $model_path ]]; then current=$(sha256sum "$model_path" | cut -d' ' -f1); fi
    if [[ -n $current && $current != "$model_sha256" ]]; then
      report_error 'existing model checksum differs; preserve or relocate it before preparation'
      exit 1
    fi
    progress_finish 'done'
    if [[ -z $current ]]; then
      progress_start "Download $model_label"
      model_dir=$(dirname "$model_path")
      model_stage="$model_dir/.nix-config-$model_file"
      [[ ! -L $model_dir ]] || { report_error 'model directory must not be a symlink'; exit 1; }
      install -d -m0755 -o0 -g0 "$model_dir"
      download_dir="$model_stage.download"
      [[ ! -e $model_stage && ! -L $model_stage ]] || { report_error 'stale model preparation stage requires operator review'; exit 1; }
      if [[ -e $download_dir || -L $download_dir ]]; then
        [[ -d $download_dir && ! -L $download_dir ]] || { report_error 'model download stage must be a directory'; exit 1; }
        printf '%s\n%s\n%s\n%s\n' "$model_repository" "$model_revision" "$model_file" "$model_sha256" | cmp -s - "$download_dir/nix-config-identity" || {
          report_error 'model download stage has a different declaration'
          exit 1
        }
      else
        install -d -m0700 -o0 -g0 "$download_dir"
        printf '%s\n%s\n%s\n%s\n' "$model_repository" "$model_revision" "$model_file" "$model_sha256" >"$download_dir/nix-config-identity"
        chmod 0600 "$download_dir/nix-config-identity"
      fi
      run_with_progress hf download "$model_repository" "$model_file" \
        --revision "$model_revision" \
        --local-dir "$download_dir"
      downloaded="$download_dir/$model_file"
      [[ -f $downloaded && ! -L $downloaded ]] || { report_error 'Hugging Face download did not produce the declared file'; exit 1; }
      progress_finish 'done'
      progress_start "Verify $model_label"
      printf '%s  %s\n' "$model_sha256" "$downloaded" | sha256sum --check --status
      progress_finish 'done'
    fi
    progress_start "Publish receipt for $model_label"
    if [[ -z $current ]]; then
      chmod 0644 "$downloaded"
      run_with_progress mv -T "$downloaded" "$model_path"
      run_with_progress rm -rf -- "$download_dir"
    fi
    model_fingerprint=$(stat -Lc '%d:%i:%s:%Y:%Z' "$model_path")
    receipt_stage="$model_receipt.stage"
    [[ ! -L $model_receipt && ! -L $receipt_stage ]] || { report_error 'model receipt path must not be a symlink'; exit 1; }
    printf '%s\n%s\n%s\n%s\n%s\n' \
      "$model_repository" "$model_revision" "$model_file" "$model_sha256" "$model_fingerprint" >"$receipt_stage"
    chmod 0644 "$receipt_stage"
    chown 0:0 "$receipt_stage"
    mv -Tf "$receipt_stage" "$model_receipt"
    progress_finish 'done'
  done
fi
printf 'llama.cpp preparation complete\n'
