# RetargetLab Skill

The Skill has two independent entrances: **install the complete supported runtime**, or **use an existing installation for a selected task**. It targets CLI **0.1.0rc4**.

## Install the Skill

Use the `skills/retargetlab` folder from this repository, or unpack the `retargetlab-skill-0.1.0.zip` release asset into your coding agent's personal skills directory. The resulting `retargetlab` folder contains `SKILL.md`, four references, a self-contained installation helper, UI metadata and the MIT license.

In Codex, select `$retargetlab`. Confirm it appears in your skill list; use the skill location supported by your installed client. The Skill does not require a connector or private laboratory account.

## Install the runtime

Ask the Skill to install RetargetLab at a chosen supported Linux host/location. Installation defaults to the complete runtime, not a task-specific subset. Processing/replay and actual LeRobot reading live in separate environments to retain their compatible dependencies. No private EEF data, robot model, sampling rate or intended business task is needed for installation.

The helper is also usable directly with a verified Python 3.12 executable:

```bash
"$PY312" skills/retargetlab/scripts/install_full.py --prefix /path/to/new-installation
"$PY312" skills/retargetlab/scripts/install_full.py --prefix /path/to/installation --check
```

It verifies the pinned public CLI kit/wheel, installs all supported runtime extras, performs checks and records both interpreter paths in `installation.json`. Existing prefixes are not overwritten. `--check` does not repair or update an installation. Refer to the [installation instructions](../skills/retargetlab/references/install.md) for the exact scope and failures.

## Use it

Examples: inspect a supported data file; replay EEF on a specified supported robot; replay saved results; diagnose a run; export a dataset; verify actual reading. Specify the result you want and an input/configuration/run reference. The Skill reuses known information and asks only for missing necessary material or decisions.

EEF robot replay includes necessary IK but does not automatically include training export or dynamics. Usage checks only the installed components relevant to the task; it never implicitly installs or upgrades dependencies. Missing or conflicting inputs receive scoped, feasible choices. See [task workflows](../skills/retargetlab/references/usage.md) and [input boundaries](../skills/retargetlab/references/inputs.md).

The Skill's presence does not implement missing CLI capabilities. In particular, the current exporter's source-Joint dependency remains in force.
