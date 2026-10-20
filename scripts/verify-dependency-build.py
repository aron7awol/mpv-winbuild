"""Fail a release engine if any effective package base differs from its lock."""
import json
from pathlib import Path
import subprocess
import sys


def git(directory, *args):
    return subprocess.check_output(
        ["git", "-C", str(directory), *args], text=True
    ).strip()


def main():
    source, expected_file, output = map(Path, sys.argv[1:])
    expected = json.loads(expected_file.read_text())
    assert expected["complete"] and expected["baseline_run"] == 38436222182
    locked = {p["name"]: p["base"] for p in expected["packages"]}
    rows = []
    seen = set()
    for line in source.read_text().splitlines():
        name, base, directory, stamp = line.split("\t")
        assert name not in seen and locked[name] == base
        seen.add(name)
        recorded = (Path(stamp) / "HEAD").read_text().strip()
        assert recorded == base, f"{name}: built/reset base {recorded} != lock {base}"
        assert git(directory, "rev-parse", base + "^{commit}") == base
        subprocess.run(["git", "-C", directory, "merge-base", "--is-ancestor", base, "HEAD"], check=True)
        assert not git(directory, "status", "--porcelain", "--untracked-files=no"), f"{name}: dirty source"
        rows.append({
            "name": name, "base": base, "recorded_base": recorded,
            "head": git(directory, "rev-parse", "HEAD"),
            "tree": git(directory, "rev-parse", "HEAD^{tree}"),
            "install_stamp_present": (Path(stamp) / (name + "-install")).exists(),
        })
    assert seen == set(locked), f"Graph/lock mismatch: {seen ^ set(locked)}"
    report = {"passed": True, "baseline_run": 38436222182, "packages": rows}
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Verified all {len(rows)} effective Git bases against the .72 lock.")


if __name__ == "__main__":
    main()
