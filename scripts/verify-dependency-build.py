"""Fail a release engine if any effective package base differs from its lock."""
import json
from pathlib import Path
import subprocess
import sys
from dependency_source_state import load_baseline, source_errors, source_state


def git(directory, *args):
    return subprocess.check_output(
        ["git", "-C", str(directory), *args], text=True
    ).strip()


def main():
    source, expected_file, output = map(Path, sys.argv[1:4])
    source_baseline = load_baseline(sys.argv[4]) if len(sys.argv) == 5 else []
    expected = json.loads(expected_file.read_text())
    assert expected["complete"] and expected["baseline_run"] == 38436222182
    locked = {p["name"]: p["base"] for p in expected["packages"]}
    assert all(item["package"] in locked and
               locked[item["package"]] == item["parent_base"] for item in source_baseline)
    rows = []
    failures = []
    seen = set()
    for line in source.read_text().splitlines():
        name, base, directory, stamp = line.split("\t")
        row = {"name": name, "base": base}
        rows.append(row)
        errors = []
        if name in seen or locked.get(name) != base:
            errors.append(f"{name}: graph/lock mismatch or duplicate")
        seen.add(name)
        try:
            evidence = source_state(directory)
            row.update(head=evidence["head"], tree=evidence["tree"], source_state=evidence)
            errors.extend(source_errors(name, evidence, source_baseline))
            recorded = (Path(stamp) / "HEAD").read_text().strip()
            row["recorded_base"] = recorded
            row["install_stamp_present"] = (Path(stamp) / (name + "-install")).exists()
            if recorded != base:
                errors.append(f"{name}: built/reset base {recorded} != lock {base}")
            if git(directory, "rev-parse", base + "^{commit}") != base:
                errors.append(f"{name}: base commit differs")
            subprocess.run(["git", "-C", directory, "merge-base", "--is-ancestor", base, "HEAD"], check=True)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
        row["errors"] = errors
        failures.extend(errors)
    if seen != set(locked):
        failures.append(f"Graph/lock mismatch: {sorted(seen ^ set(locked))}")
    report = {"passed": not failures, "baseline_run": 38436222182,
              "packages": rows, "errors": failures, "source_data_baseline": source_baseline}
    output.write_text(json.dumps(report, indent=2) + "\n")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)
    print(f"Verified all {len(rows)} effective Git bases against the .72 lock.")


if __name__ == "__main__":
    main()
