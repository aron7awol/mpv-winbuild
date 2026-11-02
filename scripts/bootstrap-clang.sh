#!/usr/bin/env bash
# Explicit cold-cache recovery; never treat a compiler alone as a complete SDK.
set -euo pipefail
test "${1:?architecture required}" = 64
wrapper_root="$(pwd)"
buildroot="$wrapper_root/mpv-winbuild-cmake"
clang_root="$buildroot/clang_root"
sysroot="$buildroot/build64/install/x86_64-w64-mingw32"
lock="$wrapper_root/scripts/bootstrap-clang.json"
version=$(python -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$lock")
if [ -x "$clang_root/bin/clang" ]; then
  test "$("$clang_root/bin/clang" -dumpversion)" = "$version"
else
  test ! -e "$clang_root/bin/clang"
  url=$(python -c 'import json,sys;print(json.load(open(sys.argv[1]))["url"])' "$lock")
  digest=$(python -c 'import json,sys;print(json.load(open(sys.argv[1]))["sha256"])' "$lock")
  archive="$buildroot/llvm-official.tar.xz"
  curl --fail --location --retry 3 "$url" -o "$archive"
  printf '%s  %s\n' "$digest" "$archive" | sha256sum --check --strict
  mkdir -p "$clang_root"
  tar -xJf "$archive" --strip-components=1 -C "$clang_root"
  rm -- "$archive"
fi
"$clang_root/bin/clang" --version
test "$("$clang_root/bin/clang" -dumpversion)" = "$version"
cd "$buildroot"
cmake -Wno-dev --fresh -G Ninja -S . -B build64 \
  -DTARGET_ARCH=x86_64-w64-mingw32 -DCOMPILER_TOOLCHAIN=clang \
  -DCMAKE_INSTALL_PREFIX="$clang_root" -DMINGW_INSTALL_PREFIX="$sysroot" \
  -DCLANG_PACKAGES_LTO=OFF -DSINGLE_SOURCE_LOCATION="$buildroot/src_packages" \
  -DRUSTUP_LOCATION="$buildroot/install_rustup"
ninja -C build64 llvm-download
test "$(git -C src_packages/llvm rev-parse HEAD)" = \
  "$(python -c 'import json,sys;print(json.load(open(sys.argv[1]))["llvm_commit"])' "$lock")"
ninja -C build64 llvm-clang
test -f "$sysroot/lib/libkernel32.a"
test -f "$sysroot/lib/libc++.a"
export PATH="$clang_root/bin:$PATH"
printf '#include <windows.h>\nint main(void) { return GetCurrentProcessId() == 0; }\n' > build64/probe.c
printf '#include <vector>\n#include <thread>\nint main() { std::vector<int> v{1}; std::thread t([]{}); t.join(); return v[0] - 1; }\n' > build64/probe.cpp
x86_64-w64-mingw32-clang build64/probe.c -o build64/probe-c.exe
x86_64-w64-mingw32-clang++ build64/probe.cpp -o build64/probe-cxx.exe
python - "$lock" "$buildroot" <<'PY'
import json, pathlib, subprocess, sys
lock = json.loads(pathlib.Path(sys.argv[1]).read_text())
root = pathlib.Path(sys.argv[2])
proof = {"lock": lock, "source_commits": {}, "compiler": subprocess.check_output([str(root / "clang_root/bin/clang"), "--version"], text=True), "link_probes": ["C Windows API", "C++ vector/thread"]}
for name, key in [("llvm", "llvm_commit"), ("mingw-w64", "mingw_commit"), ("cppwinrt", "cppwinrt_commit")]:
    actual = subprocess.check_output(["git", "-C", str(root / "src_packages" / name), "rev-parse", "HEAD"], text=True).strip()
    assert actual == lock[key], (name, actual)
    proof["source_commits"][name] = actual
(root / "build64/toolchain-bootstrap.json").write_text(json.dumps(proof, indent=2) + "\n")
PY
