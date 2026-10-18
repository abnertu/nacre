# usage: zsh -f zsh-complete.zsh <completion-dir> <command line>
# Types the line into an interactive zsh, presses Tab and prints each
# candidate the completion system adds, one per line.
zmodload zsh/zpty
zpty z zsh -f -i
zpty -w z "PROMPT=; RPROMPT=; fpath=(${(q)1} \$fpath); autoload -U compinit; compinit -u -D"
zpty -w z 'M=$(printf "\x01"); E=$(printf "\x02")'
zpty -w z 'compadd() { local -a __a; builtin compadd -O __a "$@"; print -l -- ${__a/#/$M}; builtin compadd "$@" }'
zpty -w z 'comppostfuncs=(_end); _end() { print -- "${E}done" }'
zpty -w -n z "$2"$'\t'
local line out
while zpty -r z line; do
  line=${line//$'\r'}
  [[ $line == *$'\x02'done* ]] && break
  [[ $line == *$'\x01'* ]] && out+="${line##*$'\x01'}"$'\n'
done
zpty -d z
print -rn -- $out
