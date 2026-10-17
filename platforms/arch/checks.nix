{
  pkgs,
  llama-prepare,
  aiManifest,
  adapterPython ? pkgs.python3,
  progress ? import ../../lib/cli/progress { inherit pkgs adapterPython; },
  ...
}:
{
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
        python ${./ai/tests/test_ai.py} ${./ai/package-caddy.Caddyfile} ${./ai/runtime.py}
        touch "$out"
      '';
  ai-generated-artifacts =
    pkgs.runCommand "ai-generated-artifacts" { nativeBuildInputs = [ adapterPython ]; }
      ''
        python ${./ai/tests/test_generated.py} ${aiManifest} ${./ai/package-caddy.Caddyfile}
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
  personal-agent-tests =
    pkgs.runCommand "personal-agent-tests" { nativeBuildInputs = [ adapterPython ]; }
      ''
        python ${./personal-agent/tests/test_personal_agent.py} ${./personal-agent/adapter.py}
        touch "$out"
      '';
  llama-prepare-interface =
    pkgs.runCommand "llama-prepare-interface"
      {
        PROGRESS_TEST_SHELL = ./../../lib/cli/progress/progress.sh;
        PROGRESS_TEST_RENDERER = "${progress.renderer}/bin/progress-renderer";
        nativeBuildInputs = [
          pkgs.python3
          pkgs.util-linux
        ];
      }
      ''
        ${llama-prepare}/bin/llama-prepare --help | grep -Fxq \
          'usage: llama-prepare [--build-only | --model-only]'
        if ${llama-prepare}/bin/llama-prepare --model-only >out 2>err; then exit 1; fi
        grep -Fq 'run llama-prepare as root' err
        python ${../../modules/ai/tests/test_prepare.py} ${../../modules/ai/prepare.sh}
        touch "$out"
      '';
  arch-switch-tests =
    pkgs.runCommand "arch-switch-tests"
      {
        nativeBuildInputs = with pkgs; [
          python3
          bash
          coreutils
          diffutils
          findutils
          gawk
          gnugrep
          gnused
          util-linux
        ];
        PROGRESS_TEST_SHELL = ./../../lib/cli/progress/progress.sh;
        PROGRESS_TEST_RENDERER = "${progress.renderer}/bin/progress-renderer";
      }
      ''
        python ${./tests}/test_arch_switch.py ${./.}/arch-switch.sh
        python ${./tests}/test_optional_lifecycle.py ${./.}/arch-switch.sh
        touch "$out"
      '';
}
