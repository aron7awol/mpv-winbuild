"""Recover source commits, not binaries, from the exact cache used by release .72.

For tracked refs that moved in .72, the recorded .72 job's fetch destination
is authoritative. For refs with no fetch movement in that job, its immutable
input cache's tracking ref is authoritative. Pins override both. This helper
does not check out sources, modify build recipes, build, publish, or save caches.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from dependency_source_state import source_state


def git(directory, *args, check=True):
    result = subprocess.run(
        ["git", "-c", f"safe.directory={directory}", "-C", str(directory), *args],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if check and result.returncode:
        raise RuntimeError(f"{directory.name}: git {args[0]} failed: {result.stderr[-2000:]}")
    return result.stdout.strip() if result.returncode == 0 else None


def main():
    source, request_file, output = map(Path, sys.argv[1:])
    request = json.loads(request_file.read_text())
    assert request["previousRun"] == 38436222182
    assert request["sourceCache"] == "source-2026-09-09-34393354351-1"
    if os.environ.get("GITHUB_ACTIONS"):
        assert os.environ.get("BASELINE_CACHE_HIT") == "true"
    records = []
    # Snapshot every tracking ref before fetching anything.
    for package in request["packages"]:
        name = package["name"]
        assert re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name)
        directory = source / name
        if not (directory / ".git").exists():
            raise RuntimeError(f"Missing {name} in the exact .72 input cache")
        tracking = git(directory, "rev-parse", "--symbolic-full-name", "@{u}", check=False)
        tracking_sha = git(directory, "rev-parse", "@{u}^{commit}", check=False)
        cached_head = git(directory, "rev-parse", "HEAD")
        expected = package.get("previous")
        if expected:
            method = "explicit-recipe-pin" if package["policy"] == "explicit-pin" else "release-072-fetch-destination"
        else:
            if not tracking_sha:
                raise RuntimeError(f"{name}: no .72 log destination and no cached tracking ref")
            expected = tracking_sha
            method = "unchanged-tracking-ref-in-exact-release-072-input-cache"
        assert re.fullmatch(r"[0-9a-f]{7,40}", expected)
        records.append({
            "name": name, "repository": package["repository"],
            "expected": expected, "method": method,
            "cached_head": cached_head, "cached_tracking_ref": tracking,
            "cached_tracking_sha": tracking_sha,
            "cached_source_state": source_state(directory),
        })
    result = {
        "baseline_release": "0.41.0.72", "baseline_run": request["previousRun"],
        "source_cache": request["sourceCache"],
        "recovery_run": os.environ.get("GITHUB_RUN_ID"),
        "request_log_sha256": request["previousLogSha256"],
        "packages": records,
    }
    output.write_text(json.dumps(result, indent=2) + "\n")
    if os.environ.get("BASELINE_SNAPSHOT_ONLY") == "true":
        print(f"Captured {len(records)} cached source/submodule states without fetching or modifying sources.")
        return
    # Fetch only to resolve immutable log IDs not already present in the cache.
    # Floating HEADs fetched here never select the baseline. Some cached repos
    # are shallow, so a normal fetch does not make the prior release reachable.
    for record in records:
        directory = source / record["name"]
        expected = record["expected"]
        resolved = git(directory, "rev-parse", "--verify", expected + "^{commit}", check=False)
        if resolved is None:
            shallow = git(directory, "rev-parse", "--is-shallow-repository") == "true"
            git(directory, "fetch", *(["--unshallow"] if shallow else []),
                "--filter=tree:0", "--no-recurse-submodules", "origin")
            resolved = git(directory, "rev-parse", "--verify", expected + "^{commit}")
        assert re.fullmatch(r"[0-9a-f]{40}", resolved) and resolved.startswith(expected)
        record["base"] = resolved
        output.write_text(json.dumps(result, indent=2) + "\n")
        print(f"{record['name']} {resolved} [{record['method']}]", flush=True)
    result["complete"] = True
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Recovered {len(records)} exact dependency/source bases; no build or publication.")


if __name__ == "__main__":
    main()
