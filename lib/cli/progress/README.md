# Task progress

One Rich progress display shared by the workstation's Bash and Python tools: running tasks update in place, finished results and durations stay in scrollback. Callers own task execution, child I/O, errors and recovery; this module only renders. The Python implementation lives in `nix-adapter`; this directory provides the Bash side.

## Python

```python
from nix_adapter import Progress

with Progress("Example") as progress:
    with progress.task("Check sample inputs", total=3) as task:
        for completed in range(1, 4):
            task.update(completed)
    with progress.task("Run a sample child") as task:
        with task.external_output():
            subprocess.run([...], check=True)
```

A `task` context records success or failure without swallowing exceptions. `task.update(completed, total=...)` reports real progress, `task.finish("skip")` records an explicit skip. Enter `task.external_output()` before a child writes to the terminal: it clears and pauses the display, then resumes. Task labels are fixed text: never put arguments, environment variables or credentials in them.

## Bash

Import [default.nix](default.nix) with `{ inherit pkgs adapterPython; }`. It provides the renderer (`renderer`) and a Bash prelude (`shell`) to put before the application source in `writeShellApplication`.

```bash
progress_init "Example" 0  # second argument: verbose (0 or 1)
trap 'status=$?; progress_exit "$status"' EXIT
progress_start "Check sample inputs" 3
for completed in 1 2 3; do
  progress_update "$completed"
done
progress_finish 'done'
```

- `progress_suspend` / `progress_resume` hand the terminal to another writer; suspend returns after the renderer confirms.
- `progress_finish` takes `done`, `skip` or `failed`.
- `progress_exit` closes the renderer with the saved exit status; call it from your own cleanup if you have one.
- Call `progress_close` before `exec` so the new process reports its own result.

The Bash side uses a dedicated control channel: it never reads stdin or redirects child output. A display failure never replaces the application's result.

## Terminal behavior

Progress goes to stderr. Non-terminal output, verbose mode, `TERM=dumb`, any `NO_COLOR` or a non-empty `CI` switch to plain status lines. The display uses normal scrollback, not the alternate screen. Renderer tests live in `nix-adapter` (`nix flake check github:gin31259461/nix-adapter`). See [deployment](../../../docs/deployment.md#progress-and-diagnostics) for how workstation commands use it.
