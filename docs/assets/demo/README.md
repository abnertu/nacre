# Record the terminal demo

Use the current machine flake on Arch Linux.
Build `nacre` from this checkout, then run from the repository root:

```bash
nix shell github:NixOS/nixpkgs/4fe25e12eb9f4c744966dd3de5a05246cf098601#asciinema-agg -c python3 docs/assets/demo/record.py \
  --machine /path/to/machine-flake --command /path/to/bin/nacre
```

The recorder runs `nacre --version`, `nacre status` and `nacre build` against that machine flake.
Build does not activate the deployment.
The included GIF shows a development build of Nacre 0.10.0 and Home Manager generation 104.
The machine's Babu preflight reads service credentials, so this recording excludes `nacre plan`.

The recorder captures actual stdout and stderr in memory.
The [filter](redact.py) removes personal identifiers before logging or rendering.
Unsupported controls, invalid text and oversized output reject the recording.
The filter covers account names, hostnames, home paths, email addresses, endpoints and private addresses.
Review other identifying information manually.

[agg](https://github.com/asciinema/agg) renders the sanitized transcript with a neutral prompt.
Timing is edited for readability; command output stays unchanged except for redaction.
No native commands or machine observations are substituted.
The recorder replaces `docs/assets/demo.gif` only after every command and rendering step succeeds.
Temporary transcripts are removed on exit.

Inspect the beginning, middle and end frames before committing the GIF.
Check complete output, personal identifiers, duration and looping.
Never run recording automatically.
