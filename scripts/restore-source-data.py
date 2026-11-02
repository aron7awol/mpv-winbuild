"""Restore explicitly locked source data on a cold cache, then audit normally."""
import json
from pathlib import Path
import subprocess
import sys
from dependency_source_state import load_baseline, source_state, source_errors


def run(directory, *args):
    return subprocess.check_output(["git", "-C", str(directory), *args], text=True).strip()


def restore(source, baseline_file):
    records = load_baseline(baseline_file)
    for item in records:
        parent = Path(source) / item["package"]
        child = parent / item["path"]
        assert run(parent, "rev-parse", "HEAD") == item["parent_base"]
        assert run(parent, "rev-parse", "HEAD^{tree}") == item["parent_tree"]
        assert run(parent, "ls-files", "--stage", "--", item["path"]).split()[1] == item["gitlink"]
        if not (child / ".git").exists():
            run(parent, "submodule", "update", "--init", "--", item["path"])
        assert not run(child, "status", "--porcelain"), "Refusing dirty source data"
        actual = run(child, "rev-parse", "HEAD")
        assert actual in (item["gitlink"], item["head"]), "Unexpected source-data revision"
        if actual != item["head"]:
            run(child, "fetch", "--no-tags", "origin", item["head"])
            run(child, "checkout", "--detach", item["head"])
        errors = source_errors(item["package"], source_state(parent), records)
        assert not errors, errors
        print(f'Restored locked {item["package"]}/{item["path"]}: {item["head"]}')


if __name__ == "__main__":
    restore(*sys.argv[1:])
