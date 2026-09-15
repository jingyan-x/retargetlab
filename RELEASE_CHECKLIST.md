# v0.1 release handoff

- [x] Prepare the isolated `codex/v0.1-release` worktree from the existing repository.
- [x] Build the 0.1.0rc4 wheel, source kit, install kit and SHA256 checksums.
- [x] Run the installed-wheel public-model smoke workflow with both backends and the separate actual LeRobot reader.
- [x] Run development regression and final-float32 native-clearance boundary tests.
- [x] Prepare a pinned-action GitHub workflow for validation, artifact upload and tagged release publication.
- [ ] Confirm the project license and publication destination. The existing origin is `jingyan-x/retargetlab`.
- [ ] Add the chosen LICENSE and update release notes to remove the pending-license notice.
- [ ] Push the release branch, open the review, and observe GitHub-hosted validation.
- [ ] Tag the exact validated version and verify the resulting GitHub Release and asset hashes.

The workflow has been checked locally; no GitHub-hosted run or public release is claimed before it is pushed. Tag publication is blocked when the project LICENSE is absent or the tag does not match the package version. Private MQ03 datasets and experimental assets stay outside the release kit.
