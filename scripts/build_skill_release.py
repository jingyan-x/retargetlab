"""Build the reproducible public Skill artifact from an explicit file list."""

import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

VERSION = "0.1.0"
FILES = (
    "SKILL.md",
    "LICENSE",
    "agents/openai.yaml",
    "references/install.md",
    "references/usage.md",
    "references/inputs.md",
    "references/decisions.md",
    "scripts/install_full.py",
)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--dist", type=Path, default=Path("skill-dist"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    skill = root / "skills/retargetlab"
    dist = args.dist.resolve()
    forbidden = (
        b"/data_" + b"ssda/",
        b"lab-container-" + b"via-platform",
        b"C:/" + b"Users/",
        b"C:\\" + b"Users\\",
    )
    data_extensions = {".parquet", ".mp4", ".mkv", ".avi", ".h5", ".hdf5", ".npy", ".npz"}
    tracked = subprocess.check_output(["git", "ls-files"], cwd=root, text=True).splitlines()
    for name in tracked:
        path = root / name
        if not path.is_file():
            continue
        if Path(name).suffix.lower() in data_extensions:
            raise ValueError(f"data file must not be tracked in this public release: {name}")
        if name.startswith(("docs/evidence/", "docs/archive/", "projects/", "runs/")):
            raise ValueError(f"internal research artifact tracked: {name}")
        if any(value in path.read_bytes() for value in forbidden):
            raise ValueError(f"laboratory-specific location found in public file: {name}")
    contents = {name: (skill / name).read_bytes() for name in FILES}
    if not contents["SKILL.md"].startswith(b"---\nname: retargetlab\n"):
        raise ValueError("unexpected Skill metadata")
    for name, data in contents.items():
        if any(value in data for value in forbidden):
            raise ValueError(f"private path in Skill: {name}")
        if name.endswith(".md"):
            for target in re.findall(r"\[[^\]\n]*\]\(([^\s)]+)\)", data.decode()):
                parsed = urlsplit(target)
                if (
                    not parsed.scheme
                    and parsed.path
                    and not (skill / name).parent.joinpath(unquote(parsed.path)).exists()
                ):
                    raise ValueError(f"broken Skill reference: {name} -> {target}")
    dist.mkdir(parents=True, exist_ok=True)
    archive_path = dist / f"retargetlab-skill-{VERSION}.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name in FILES:
            entry = zipfile.ZipInfo("retargetlab/" + name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, contents[name])
    sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    (dist / "SHA256SUMS").write_text(f"{sha}  {archive_path.name}\n")
    print(
        json.dumps(
            {
                "skill_version": VERSION,
                "cli_baseline": "0.1.0rc4",
                "archive": archive_path.name,
                "sha256": sha,
                "files": len(FILES),
                "public_tree_check": "PASSED",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
