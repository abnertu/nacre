# The operator command. It addresses any machine flake through #deployment, so
# the home generation that installs it does not depend on the deployment.
{
  lib,
  pkgs,
}:
let
  python = pkgs.python3;
  version = lib.trim (builtins.readFile ../../../VERSION);
  runnerPublicFiles = pkgs.writeText "nacre-runner-public-files.nix" ''
    { root, configFilesJSON }:
    let
      lib = import ${pkgs.path + "/lib"};
      public = import ${../../../modules/gitlab-runner/public-files.nix} {
        inherit lib;
        root = /. + root;
        configFiles = builtins.fromJSON configFilesJSON;
      };
      relative = map (lib.removePrefix "''${public.source}/") public.configFiles;
    in { capture = {
      source = toString public.source;
      declaration = "  services.gitlabRunner.configFiles = [\n"
        + lib.concatMapStringsSep "\n"
          (file: "    (./runners + "
            + lib.replaceStrings [ "\r" ] [ "\\r" ] (lib.generators.toPretty { multiline = false; } ("/" + file))
            + ")") relative
        + "\n  ];";
    }; }
  '';

  # The nacre package, with the version and the machine template substituted.
  package = python.pkgs.toPythonModule (
    pkgs.runCommand "nacre-package" { } ''
      package="$out/${python.sitePackages}/nacre"
      mkdir -p "$package"
      cp ${./nacre}/*.py "$package/"
      substituteInPlace "$package/cli.py" --subst-var-by version ${lib.escapeShellArg version}
      substituteInPlace "$package/install.py" --subst-var-by templates ${../../../templates/machine}
      substituteInPlace "$package/install.py" --subst-var-by runner-public-files ${runnerPublicFiles}
    ''
  );
  environment = python.withPackages (_: [ package ]);
in
pkgs.runCommand "nacre"
  {
    nativeBuildInputs = [ pkgs.makeWrapper ];
    meta.mainProgram = "nacre";
  }
  ''
    install -Dm644 ${./completions/_nacre} "$out/share/zsh/site-functions/_nacre"
    install -Dm644 ${./completions/nacre.bash} "$out/share/bash-completion/completions/nacre"
    makeWrapper ${environment}/bin/python3 "$out/bin/nacre" \
      --add-flags "-I -B -m nacre" \
      --prefix PATH : ${lib.makeBinPath [ pkgs.git ]}
  ''
