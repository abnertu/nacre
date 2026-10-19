# bash completion for nacre. Keep the commands in step with `nacre --help`;
# tests/test_completions.py checks this file against it.

_nacre() {
  local cur=${COMP_WORDS[COMP_CWORD]} prev=${COMP_WORDS[COMP_CWORD - 1]}
  local commands="install plan switch update purge status doctor changes generations rollback check build ai noctalia"
  local i command='' args=()
  # The command follows the global options; collect its positional arguments.
  for ((i = 1; i < COMP_CWORD; i++)); do
    case ${COMP_WORDS[i]} in
      --flake) ((i++)) ;;
      --override-input) ((i += 2)) ;;
      -*) ;;
      *) if [[ -z $command ]]; then command=${COMP_WORDS[i]}; else args+=("${COMP_WORDS[i]}"); fi ;;
    esac
  done
  local position=${#args[@]}

  if [[ $prev == --flake ]]; then
    mapfile -t COMPREPLY < <(compgen -d -- "$cur")
    return
  fi
  if [[ -z $command ]]; then
    [[ $cur == -* ]] && commands='--flake --override-input --verbose --help --version'
    mapfile -t COMPREPLY < <(compgen -W "$commands" -- "$cur")
    return
  fi

  local words=''
  case $command in
    install)
      case $prev in
        --role) words='minimal workstation' ;;
        --user | --hostname | --timezone | --locale) return ;;
        *) words='--user --hostname --role --timezone --locale --yes --force' ;;
      esac
      ;;
    changes) ((position == 0)) && words='--since' ;;
    rollback)
      local profiles=${XDG_STATE_HOME:-$HOME/.local/state}/nix/profiles link
      for link in "$profiles"/home-manager-*-link; do
        [[ -L $link ]] || continue
        link=${link##*/home-manager-}
        words+=" ${link%-link}"
      done
      ;;
    ai) case $position in 0) words='prepare' ;; 1) words='build model' ;; esac ;;
    noctalia)
      case ${args[0]:-} in
        '') words='capture deploy' ;;
        capture) words='--dry-run --check' ;;
        deploy) words='--dry-run --replace-overrides --recover' ;;
      esac
      ;;
  esac
  mapfile -t COMPREPLY < <(compgen -W "$words" -- "$cur")
}

complete -F _nacre nacre
