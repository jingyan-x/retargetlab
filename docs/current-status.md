# Current public capabilities

The CLI baseline is **0.1.0rc4 (MIT prerelease)**. The accompanying **RetargetLab Skill 0.1.0** provides separate complete-installation and usage workflows.

Supported: the registered OpenArm EEF sidecar and MQ03 EEF layouts; Pink/Pinocchio and Mink/MuJoCo; saved-joint WebGL replay; explicit quality masks; LeRobot export and actual reader verification. Skill usage performs only the selected task and does not implicitly install dependencies.

The current exporter still requires its source-Joint reference inputs. The OpenArm identity adapter requires matching source/target model fingerprints. A standalone raw-EEF 3D viewer, generic unknown-layout adaptation, automatic repair/task scheduling, dynamics, training and hardware execution are not delivered by this release.

Robot replay consumes saved solutions. Browser controls do not start IK, retune the solver or export datasets. The Skill includes necessary IK when the user requests replay from EEF and no valid solution exists.

Private laboratory datasets support internal development; their contents and results are not the public reproducibility package. See [data policy](data-policy.md) and [public validation](v0.1-acceptance.md).
