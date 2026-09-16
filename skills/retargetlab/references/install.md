# Installation workflow

This entrance is independent of usage. Install **all supported runtime components** of the verified release, regardless of which task the user may later perform.

## Establish location, not a data task

Reuse an explicitly selected host and installation location. Otherwise identify the current host and ask only when the destination is ambiguous. Installation needs no EEF dataset, source robot, reference joints, calibration records or task scenario.

Supported installation: Linux x86_64, Python 3.12, access to the official release/Python package indexes. Windows users can select an accessible supported Linux host. Do not silently install WSL, change operating systems, or create a remote machine. GPU/CUDA is not required by this CPU release.

If the chosen execution host differs from where the skill files are installed, transfer the self-contained `scripts/install_full.py` to that host's task directory (or reuse its matching copy) and execute it there. Use host-native paths; a Windows skill path is not a Linux executable path. The resulting installation record belongs to that host and contains its actual interpreter paths.

The full runtime uses two isolated environments:

- `process`: CLI, Pink/Pinocchio, Mink/MuJoCo, model and collision processing (including CoACD), plotting, WebGL replay support, video and dataset export. Extras: `pipeline,collision-mesh,viz`.
- `reader`: the same CLI version, LeRobot, CPU PyTorch/torchvision, PyAV and reader dependencies. Extra: `lerobot`.

Both are required for a complete installation. Development-only lint/test tools and unimplemented future backends are not runtime components. Robot assets and user datasets are separate usage inputs.

## Install the pinned complete runtime

Resolve `SKILL_DIR` to this installed skill directory and `INSTALL_DIR` to the chosen **new** installation prefix. Set `BOOTSTRAP_PY` to a real Python 3.12 executable after checking its version; the command name `python3.12` is not guaranteed to be on PATH. An existing installation's process interpreter can also run this helper. The commands below are examples with those values already resolved:

```bash
"$BOOTSTRAP_PY" "$SKILL_DIR/scripts/install_full.py" --prefix "$INSTALL_DIR"
```

The helper downloads the official 0.1.0rc4 kit, verifies its pinned SHA256 and the embedded wheel, installs the two full environments using the kit's constraints, runs dependency/import/CLI checks, and records exact environment paths and installed package versions.

If the official kit is already available, avoid downloading it again:

```bash
"$BOOTSTRAP_PY" "$SKILL_DIR/scripts/install_full.py" --prefix "$INSTALL_DIR" --kit /path/to/retargetlab-0.1.0rc4-kit.zip
```

The kit is verified even when provided locally. Do not bypass a hash mismatch or silently replace the release with another build. Current hashes are pinned in the helper; a new supported release requires updating the skill and validating its installation.

Expected successful artifacts:

- `installation.json`: `status=COMPLETE`, version and both Python paths.
- `installation-check.json`: both doctor results, dependency checks and full-runtime imports.
- `process-freeze.txt`, `reader-freeze.txt`: exact resolved packages.
- `logs/`: installation command logs.
- `release/`: the verified kit's contents, including installation constraints.

The helper leaves an existing prefix untouched. Platform, existing-prefix or missing-local-kit failures happen before a new installation is created; report the returned error and do not claim a log or new manifest exists. Failures after the new prefix is created record `INCOMPLETE`. Report the actual failing step and any log that exists; download, hash or final-check failures may have only the returned error/manifest. Never report a partial attempt as “installed”. Diagnose the concrete cause before another attempt. For repair, prefer a new installation directory, preserving the old environment and all user runs. Do not edit shell startup files or change global Python/PATH.

## Verify and finish

```bash
"$BOOTSTRAP_PY" "$SKILL_DIR/scripts/install_full.py" --prefix "$INSTALL_DIR" --check
```

`--check` checks the complete installation without pip installation/update or changes to the environment. It is also the entry available to usage for verification. For older manually installed environments without `installation.json`, inspect their explicit interpreters and corresponding doctor output; do not manufacture a complete-installation record or reinstall without authorization.

Installation ends with the verified version, both environment paths and self-check outcome. Public synthetic tests may validate the installation when appropriate; user datasets are never automatically processed. If the user also explicitly requested usage, return to that separately confirmed task.
