{
  pkgs,
  arch-switch,
  llama-prepare,
  adapterPython ? pkgs.python3,
  ...
}:
{
  # Nix and the adapters agree on every manifest's keys.
  adapter-manifests =
    pkgs.runCommand "adapter-manifests" { nativeBuildInputs = [ adapterPython ]; }
      ''
        python - <<'PY'
        import importlib.util
        import json
        import sys

        def load(path, name):
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

        from nix_adapter import validate

        for directory, schema, manifest in (
            ("${./core}", "CoreManifest", "${arch-switch.manifests.core}"),
            ("${./system}", "SystemManifest", "${arch-switch.manifests.system}"),
            ("${./ai}", "AIManifest", "${arch-switch.manifests.ai}"),
        ):
            data = json.load(open(manifest))
            module = load(directory + "/schema.py", schema)
            if schema == "AIManifest" and not data["llama"]:
                schema = "Unmanaged"
            validate(getattr(module, schema), data, manifest)
        PY
        touch "$out"
      '';
  system-firewall-integration = import ./system/tests/firewall-vm.nix {
    inherit pkgs adapterPython;
  };
  system-settings-interface =
    assert import ./system/tests/interface.nix {
      inherit pkgs;
      inherit (pkgs) lib;
    };
    pkgs.writeText "system-settings-interface" "passed";
  core-tests = pkgs.runCommand "core-tests" { nativeBuildInputs = [ adapterPython ]; } ''
    python ${./core}/tests/test_core.py
    touch "$out"
  '';
  system-settings-tests =
    pkgs.runCommand "system-settings-tests" { nativeBuildInputs = [ adapterPython ]; }
      ''
        python ${./system}/tests/test_system.py
        touch "$out"
      '';
  ai-services-tests =
    pkgs.runCommand "ai-services-tests" { nativeBuildInputs = [ adapterPython ]; }
      ''
        python ${./ai}/tests/test_ai.py ${./ai/package-caddy.Caddyfile} ${./ai}/runtime.py
        python ${./ai}/tests/test_dmem_guard.py ${./ai}/dmem_guard.py
        touch "$out"
      '';
  ai-diagnostic-tools =
    pkgs.runCommand "ai-diagnostic-tools"
      { nativeBuildInputs = [ (pkgs.python3.withPackages (python: [ python.jinja2 ])) ]; }
      ''
        python ${../../modules/ai}/tests/test_chat_template.py
        python ${../../modules/ai}/tests/test_benchmark.py
        python ${../../modules/ai}/tests/test_probe.py
        python ${../../modules/ai}/tests/test_router.py ${pkgs.llama-swap}/bin/llama-swap
        touch "$out"
      '';
  llama-prepare-interface =
    pkgs.runCommand "llama-prepare-interface" { nativeBuildInputs = [ adapterPython ]; }
      ''
        if ${llama-prepare}/bin/llama-prepare --model-only >out 2>err; then exit 1; fi
        grep -Fq 'run llama-prepare as root' err
        python ${../../modules/ai/tests/test_prepare.py} ${../../modules/ai/prepare.py}
        touch "$out"
      '';
  arch-switch-tests =
    pkgs.runCommand "arch-switch-tests" { nativeBuildInputs = [ adapterPython ]; }
      ''
        python ${./tests}/test_arch_switch.py ${./switch.py}
        python ${./tests}/test_optional_lifecycle.py ${./switch.py}
        touch "$out"
      '';
}
