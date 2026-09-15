"""Allow the same CLI through python -m retargetlab."""

from retargetlab.cli.main import app

if __name__ == "__main__":
    raise SystemExit(app())
