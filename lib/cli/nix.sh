# Sourced by Just recipes before Nix builds the runtime progress module.
# Callers choose privilege and the preserved environment; helpers add diagnostics.
nix_progress_init() {
  nix_progress_args=(--log-format raw)
  if [[ -t 2 && ${TERM:-dumb} != dumb && ! -v NO_COLOR && -z ${CI:-} ]] &&
    [[ ${1:-0} == 0 ]]; then
    nix_progress_args=(--log-format bar-with-logs)
  fi
}

# Replace the recipe with a Nix subcommand that keeps complete diagnostics.
nix_exec() {
  [[ -v nix_progress_args ]] || nix_progress_init
  exec nix "${nix_progress_args[@]}" "$1" --show-trace --print-build-logs "${@:2}"
}

# As nix_exec, through sudo preserving only the named environment variables.
nix_exec_root() {
  [[ -v nix_progress_args ]] || nix_progress_init
  exec sudo --preserve-env="$1" nix "${nix_progress_args[@]}" \
    --extra-experimental-features 'nix-command flakes' "$2" --show-trace --print-build-logs "${@:3}"
}
