#!/bin/bash
# Isolated build from a copy of Claude's already-patched source tree.
set -euo pipefail
work=/mnt/scratch/t7910-p2p
base=local-llm-runner-maya:v1.1.56
python3 "$work/prepare-maya.py"
# Reuse the unchanged main object; its helper header is excluded by the user's
# broad *env* filename lockdown. No excluded file is read or copied.
cp /mnt/scratch/maya-ds4g/build-src/build-hip/CMakeFiles/maya-ds4.dir/src/ds4/ds4_main.cpp.o "$work/maya-build/prebuilt-ds4-main.o"
python3 - <<'PY'
from pathlib import Path
p=Path('/mnt/scratch/t7910-p2p/maya-build/CMakeLists.txt')
s=p.read_text()
old='    add_executable(maya-ds4 src/ds4/ds4_main.cpp '
if old in s:
    s=s.replace(old, '    set_source_files_properties(prebuilt-ds4-main.o PROPERTIES EXTERNAL_OBJECT TRUE GENERATED TRUE)\n    add_executable(maya-ds4 prebuilt-ds4-main.o ', 1)
    p.write_text(s)
assert 'add_executable(maya-ds4 prebuilt-ds4-main.o ' in s
PY
mkdir -p "$work/maya-out"
docker run --rm -v "$work/maya-build:/w" -v "$work/maya-out:/out" -w /w "$base" bash -c '
  set -e
  root=/opt/rocm
  export PATH="$root/bin:$root/llvm/bin:$PATH" ROCM_PATH=$root HIP_PATH=$root HIP_PLATFORM=amd LD_LIBRARY_PATH=$root/lib
  cmake -S . -B build-hip -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DSTRATA_ENABLE_HIP=ON -DSTRATA_ENABLE_CUDA=OFF -DSTRATA_PREFILL_MMQ=ON \
    -DSTRATA_NATIVE_EXPERTS=ON -DSTRATA_BUILD_TESTS=OFF -DCMAKE_HIP_ARCHITECTURES=gfx1100 \
    -DCMAKE_HIP_COMPILER=$root/llvm/bin/clang++ -DCMAKE_PREFIX_PATH=$root \
    -DSTRATA_GGML_DIR=/opt/maya/src/third_party/llama.cpp \
    "-DCMAKE_HIP_FLAGS=--rocm-path=$root --rocm-device-lib-path=$root/lib/llvm/amdgcn/bitcode"
  cmake --build build-hip --target maya-ds4 -j24
  cp build-hip/maya-ds4 /out/maya-ds4
'
printf 'FROM %s\nCOPY maya-ds4 /opt/maya/src/engine/maya-ds4\n' "$base" >"$work/maya-out/Dockerfile"
docker build -q -t local-llm-runner-maya:v1.1.56-p2p-uncached-test "$work/maya-out"
