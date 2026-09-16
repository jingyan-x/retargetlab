"""Package the public install kit without private datasets or experiment records."""

import argparse
import hashlib
import json
import tomllib
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--dist", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    dist = args.dist.resolve() if args.dist else root / "dist"
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    wheel = dist / f"retargetlab-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.startswith("retargetlab/") and not name.endswith("/"):
                if (root / "src" / name).read_bytes() != archive.read(name):
                    raise ValueError(f"wheel/source mismatch: {name}")
    names = [
        "README.md",
        "pyproject.toml",
        "RELEASE_NOTES.md",
        "docs/v0.1-usage.md",
        "docs/v0.1-acceptance.md",
        "docs/skill-guide.md",
        "docs/data-policy.md",
        "docs/current-status.md",
        "env/v0.1-process-linux-py312.txt",
        "env/v0.1-reader-linux-py312.txt",
    ]
    for optional in ("LICENSE", "NOTICE"):
        if (root / optional).is_file():
            names.append(optional)
    names += [
        "skills/retargetlab/" + name
        for name in (
            "SKILL.md",
            "LICENSE",
            "agents/openai.yaml",
            "references/install.md",
            "references/usage.md",
            "references/inputs.md",
            "references/decisions.md",
            "scripts/install_full.py",
        )
    ]
    source_files = [root / name for name in names]
    source_files += [
        p
        for p in (root / "src/retargetlab").rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and (p.suffix in (".py", ".js", ".html", ".md") or p.name == "LICENSE")
    ]
    source_files += [
        root / name
        for name in (
            ".github/workflows/release.yml",
            "scripts/release_smoke.py",
            "scripts/build_release_kit.py",
            "tests/integration/test_release.py",
            "tests/integration/test_saved_q_replay.py",
            "tests/integration/test_native_collision.py",
            "tests/browser/test_playback.mjs",
        )
    ]
    public_index = (
        "# v0.1 documentation\n\n- [Usage](v0.1-usage.md)\n- [Acceptance](v0.1-acceptance.md)\n"
    )
    notice = (
        "Project license selection pending; local release draft only.\n"
        if not (root / "LICENSE").exists()
        else "Third-party components retain their licenses.\n"
    )
    notice += "Public release tests included; private experiment datasets and harnesses excluded.\n"
    source_zip = dist / f"retargetlab-{version}-source.zip"
    with zipfile.ZipFile(source_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source_files:
            archive.write(path, path.relative_to(root).as_posix())
        archive.writestr("docs/README.md", public_index)
        archive.writestr("RELEASE-NOTICE.txt", notice)
    kit = dist / f"retargetlab-{version}-kit.zip"
    with zipfile.ZipFile(kit, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(wheel, "dist/" + wheel.name)
        archive.write(source_zip, "source/" + source_zip.name)
        for name in names:
            archive.write(root / name, name)
        archive.writestr("docs/README.md", public_index)
        archive.writestr("RELEASE-NOTICE.txt", notice)
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (wheel, source_zip, kit)}
    (dist / "SHA256SUMS").write_text("".join(f"{sha}  {name}\n" for name, sha in hashes.items()))
    print(json.dumps({"version": version, "files": hashes}, indent=2))


if __name__ == "__main__":
    main()
