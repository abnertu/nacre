# The operator command. It knows the deployment's name but not its contents,
# so the home generation that installs it does not depend on the deployment.
{
  lib,
  pkgs,
  deploymentName,
}:
pkgs.runCommand "nacre"
  {
    nativeBuildInputs = [ pkgs.makeWrapper ];
    meta.mainProgram = "nacre";
  }
  ''
    mkdir -p "$out/bin" "$out/libexec"
    substitute ${./nacre.py} "$out/libexec/nacre.py" \
      --subst-var-by deployment ${lib.escapeShellArg deploymentName} \
      --subst-var-by version ${lib.escapeShellArg (lib.trim (builtins.readFile ../../../VERSION))}
    makeWrapper ${pkgs.python3.interpreter} "$out/bin/nacre" \
      --add-flags "-I $out/libexec/nacre.py" \
      --prefix PATH : ${lib.makeBinPath [ pkgs.git ]}
  ''
