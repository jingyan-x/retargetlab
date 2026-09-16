# RetargetLab Skill 0.1.0

This release adds a reusable Skill for the published RetargetLab CLI 0.1.0rc4. Installation and usage are separate workflows: installation prepares the complete supported runtime in two isolated environments, while usage checks and operates only the components needed by the selected task without silently modifying dependencies.

The Skill covers supported EEF processing, saved-joint robot replay, diagnosis, dataset export and actual reader verification. It includes task-specific input guidance, scoped decision options, a pinned-release installation helper and MIT licensing.

Validation includes a fresh complete installation, four installer boundary tests, actual public synthetic processing/export/reader/replay checks, two CLI negative cases and an independent review of six interaction scenarios. GitHub release validation repeats installation and the public smoke workflow.

The current CLI's source-Joint export dependency and registered-layout restrictions remain explicit. This is not a new CLI binary release and does not add dynamics, training, hardware execution or arbitrary raw-EEF visualization.

The two laboratory research datasets are private and are not included. Public reproducibility uses generated data and a pinned third-party public model. MIT covers the project software, not private data or third-party assets. Internal experiment documents were removed from the current public tree; prior Git history was not rewritten.
