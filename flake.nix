{
  description = "Tipee backend for Taxi";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { nixpkgs, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (ps: [
              ps.build
              ps.setuptools
              ps.wheel
              ps.taxi
              ps.requests
            ]))
            pkgs.twine
          ];
          # release.sh re-executes itself through `nix develop` unless this is set.
          TAXI_TIPEE_DEVSHELL = "1";
        };
      });

      formatter = forAllSystems (pkgs: pkgs.nixfmt);
    };
}
