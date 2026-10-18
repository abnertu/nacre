# The operator command. It addresses any machine flake through #deployment, so
# the home generation that installs it does not depend on the deployment.
{
  lib,
  pkgs,
}:
pkgs.runCommand "nacre"
  {
    nativeBuildInputs = [ pkgs.makeWrapper ];
    meta.mainProgram = "nacre";
  }
  ''
    mkdir -p "$out/bin" "$out/libexec"
    install -Dm644 ${./completions/_nacre} "$out/share/zsh/site-functions/_nacre"
    install -Dm644 ${./completions/nacre.bash} "$out/share/bash-completion/completions/nacre"
    substitute ${./nacre.py} "$out/libexec/nacre.py" \
      --subst-var-by templates ${../../../templates/machine} \
      --subst-var-by version ${lib.escapeShellArg (lib.trim (builtins.readFile ../../../VERSION))}
    makeWrapper ${pkgs.python3.interpreter} "$out/bin/nacre" \
      --add-flags "-I $out/libexec/nacre.py" \
      --prefix PATH : ${lib.makeBinPath [ pkgs.git ]}
  ''
