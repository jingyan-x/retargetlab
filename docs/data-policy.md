# Private laboratory data and public software

The two robot datasets used for internal OpenArm and MQ03 validation are **private laboratory research data**. This description records their internal-use context; it does not create ownership, publication or redistribution rights.

## What this repository distributes

- RetargetLab source code, the Skill, installation helpers and documentation under the project's MIT License.
- Public synthetic test/demo generation, public configuration examples and validation scripts.
- References to a pinned official OpenArm model, which retains its own Apache-2.0 license; bundled Three.js retains its MIT notices.

## What is not distributed

Private recorded videos, raw EEF or Joint arrays, derived private joint trajectories, private replay/data bundles, participant/task records, laboratory paths and private dataset inventories are not release assets. The project MIT license does not grant rights to those data or to third-party robot assets.

Running the CLI locally reads the inputs you select. Skill installation downloads public software/packages and needs no private dataset. Private file locations and credentials belong in local configuration, not a public issue, example, release log or committed file.

## Reproducibility and claims

The public example uses a pinned public model and generated EEF/Joint/video data. It can exercise processing, masking, export, replay and actual loading without access to the laboratory datasets. It demonstrates software behavior; it does not independently reproduce private experiments or establish robot task success, physical safety or generalization.

Any future data release requires its own authorization, license and review of content. Calling data laboratory-private does not remove restrictions inherited from its original collection or acquisition.

Older Git revisions may contain historical planning and aggregate internal experiment references. This release removes those documents from the current public tree; it does not rewrite existing Git history. No private data release is implied.
