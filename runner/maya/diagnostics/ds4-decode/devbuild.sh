#!/bin/bash
# devbuild.sh TAG [WORK]: build maya-ds4 from WORK/src (default /mnt/scratch/maya-ds4g; a Maya checkout + local edits,
# synced from the Mac)
# inside the v1.1.56 runner image, with the image's patches applied, then layer the binary onto that image as
# local-llm-runner-maya:TAG. Run on ubt26. One heavy job at a time: nothing else should be building or benching.
set -euo pipefail
tag=$1
base=local-llm-runner-maya:v1.1.56
work=${2:-/mnt/scratch/maya-ds4g}
patches=/mnt/scratch/maya-ds4g/context/patches
cd "$work"
mkdir -p build-src out
# (incremental: build-hip stays; files the patch touched are copied back, then patched again)
rsync -a --delete --exclude build-hip src/ build-src/
for p in "$patches"/0012-*.patch; do git -C build-src apply "$p"; done
docker run --rm -v "$work/build-src:/w" -v "$work/out:/out" -w /w "$base" bash -c '
  set -e; root=/opt/rocm
  export PATH="$root/bin:$root/llvm/bin:$PATH" ROCM_PATH=$root HIP_PATH=$root HIP_PLATFORM=amd LD_LIBRARY_PATH=$root/lib
  cmake -S . -B build-hip -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DSTRATA_ENABLE_HIP=ON -DSTRATA_ENABLE_CUDA=OFF -DSTRATA_PREFILL_MMQ=ON \
    -DSTRATA_NATIVE_EXPERTS=ON -DSTRATA_BUILD_TESTS=OFF -DCMAKE_HIP_ARCHITECTURES=gfx1100 \
    -DCMAKE_HIP_COMPILER=$root/llvm/bin/clang++ -DCMAKE_PREFIX_PATH=$root \
    -DSTRATA_GGML_DIR=/opt/maya/src/third_party/llama.cpp \
    "-DCMAKE_HIP_FLAGS=--rocm-path=$root --rocm-device-lib-path=$root/lib/llvm/amdgcn/bitcode" >/dev/null
  cmake --build build-hip --target maya-ds4 -j8
  cp build-hip/maya-ds4 /out/maya-ds4'
printf 'FROM %s\nCOPY maya-ds4 /opt/maya/src/engine/maya-ds4\n' "$base" >out/Dockerfile
docker build -q -t "local-llm-runner-maya:$tag" out
echo "built local-llm-runner-maya:$tag"
