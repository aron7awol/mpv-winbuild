"""Read-only source/submodule evidence for dependency acceptance failures."""
from pathlib import Path
import json
import re
import subprocess
import sys


def git(directory, *args):
    result = subprocess.run(
        ["git", "-c", f"safe.directory={directory}", "-C", str(directory), *args],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise RuntimeError(f"{directory}: git {args[0]}: {result.stderr[-4000:]}")
    return result.stdout.rstrip("\n")


def source_state(directory, depth=0):
    directory = Path(directory).absolute()
    state = {
        "head": git(directory, "rev-parse", "HEAD"),
        "tree": git(directory, "rev-parse", "HEAD^{tree}"),
        "status": git(directory, "status", "--porcelain",
                      "--untracked-files=no", "--ignore-submodules=none"),
        "diff_raw": git(directory, "diff", "--raw", "--no-abbrev",
                        "--ignore-submodules=none"),
        "diff": git(directory, "diff", "--no-ext-diff", "--ignore-submodules=all"),
        "diff_cached": git(directory, "diff", "--cached", "--no-ext-diff",
                           "--ignore-submodules=none"),
        "submodules": [],
    }
    for entry in git(directory, "ls-files", "--stage", "-z").split("\0"):
        if not entry.startswith("160000 "):
            continue
        info, relative = entry.split("\t", 1)
        _, expected, stage = info.split()
        child = directory / relative
        item = {"path": relative, "expected": expected, "stage": stage}
        if child.is_symlink():
            item["symlink"] = str(child.readlink())
        elif (child / ".git").exists():
            if depth >= 8:
                raise RuntimeError(f"Submodule nesting limit: {child}")
            item["state"] = source_state(child, depth + 1)
        else:
            item["initialized"] = False
        state["submodules"].append(item)
    return state


def load_baseline(file):
    baseline = json.loads(Path(file).read_text())
    assert baseline["schema"] == 1 and baseline["baseline_run"] == 38436222182
    records = baseline["submodules"]
    seen = set()
    for item in records:
        key = (item["package"], item["path"])
        assert key not in seen
        seen.add(key)
        assert re.fullmatch(r"[a-z0-9][a-z0-9_-]*", item["package"])
        assert re.fullmatch(r"[a-zA-Z0-9_/-]+", item["path"])
        assert not item["path"].startswith("/") and ".." not in item["path"].split("/")
        for field in ("parent_base", "parent_tree", "gitlink", "head", "tree"):
            assert re.fullmatch(r"[0-9a-f]{40}", item[field])
    return records


def source_errors(name, state, baseline=()):
    """Accept only exact, clean baseline data checkouts; never ignore dirt."""
    errors = []
    approved = {item["path"]: item for item in baseline if item["package"] == name}
    allowed_status = set()
    children = {item["path"]: item for item in state["submodules"]}
    for relative, expected in approved.items():
        item = children.get(relative, {})
        child = item.get("state", {})
        checks = (
            state["head"] == expected["parent_base"],
            state["tree"] == expected["parent_tree"],
            item.get("stage") == "0",
            item.get("expected") == expected["gitlink"],
            child.get("head") == expected["head"],
            child.get("tree") == expected["tree"],
            child.get("status") == "",
            child.get("diff") == "",
            child.get("diff_cached") == "",
        )
        if all(checks):
            allowed_status.add(" M " + relative)
        else:
            errors.append(f"{name}/{relative}: effective .72 source-data baseline mismatch")
    for line in state["status"].splitlines():
        if line not in allowed_status:
            errors.append(f"{name}: dirty source: {line}")
    for item in state["submodules"]:
        child = item.get("state")
        if child is None:
            continue
        if item["path"] not in approved and child["head"] != item["expected"]:
            errors.append(f"{name}/{item['path']}: submodule commit differs from gitlink")
        errors.extend(source_errors(name + "/" + item["path"], child))
    return errors


def main():
    """Verify the separately locked .72 data inputs before compilation."""
    source, baseline_file, output = map(Path, sys.argv[1:])
    baseline = load_baseline(baseline_file)
    rows, errors = [], []
    for name in sorted({item["package"] for item in baseline}):
        row = {"name": name}
        rows.append(row)
        try:
            row["source_state"] = source_state(source / name)
            row["errors"] = source_errors(name, row["source_state"], baseline)
        except Exception as exc:
            row["errors"] = [f"{name}: {exc}"]
        errors.extend(row["errors"])
    output.write_text(json.dumps({
        "passed": not errors, "baseline_run": 38436222182,
        "packages": rows, "errors": errors,
    }, indent=2) + "\n")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        raise SystemExit(1)
    print(f"Verified {len(baseline)} exact .72 source-data submodule inputs before compilation.")


if __name__ == "__main__":
    main()
