"""Read-only source/submodule evidence for dependency acceptance failures."""
from pathlib import Path
import subprocess


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
