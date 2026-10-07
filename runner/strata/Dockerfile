# local-llm-runner-strata
# Niko1221/Strata: an inference engine for Qwen3.8-Flash-Next only. Here it serves Unsloth's
# UD-Q4_K_XL (real Q4_K/Q5_K experts) on the 4x 7900 XT as a layer split, the experts the cards
# cannot hold page-locked in host RAM.
#
# The toolchain is exactly the one Strata's own setup.py used for the build that was verified on
# ubt26 (2026-10-06): AMD's TheRock ROCm wheels 7.10.0a20251120 for gfx110X in a venv, the engine
# compiled for gfx1100 with -DSTRATA_MMQ_KQUANTS=ON. That flag is the whole port: the HIP CMake
# branch already instantiates the Q4_K/Q5_K MMQ prompt kernels, setup just never passed it on AMD.
# Single stage on purpose: the engine loads the ROCm libraries from the venv at run time (the
# runner sets LD_LIBRARY_PATH from it), so the venv is the runtime.
#
# Not llama-server: the container runs strata-runner.py, which turns mgmt's argv into the JSON
# config serve/server.py reads. See build_strata_args in container/backend/runtime.py.
FROM ubuntu:24.04

ARG STRATA_REPO=https://github.com/Niko1221/Strata.git
ARG STRATA_REF=v0.1.40.2
ARG ROCM_VERSION=7.10.0a20251120
ARG ROCM_INDEX=https://rocm.nightlies.amd.com/v2/gfx110X-dgpu/
# Set to a TheRock tarball to take ROCm from it instead of the pip wheels (rocmunslothsrc does the same): e.g.
# ROCm 10.0.0, whose hipBLASLt 1.4.1 matches tools/hip/gfx1100-hipblaslt-100401.txt (small-chunk rows, #1289)
ARG ROCM_TARBALL=https://rocm.nightlies.amd.com/tarball-multi-arch/therock-dist-linux-gfx110X-all-10.0.0a20260730.tar.gz
ARG GPU_TARGETS=gfx1100
# hipcc peaks several GB per TU; -j$(nproc) OOM-kills the clang backend on this 60 GB box.
ARG BUILD_JOBS=8
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential ca-certificates curl git python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN set -e; python3 -m venv /opt/strata/venv; \
    if [ -n "$ROCM_TARBALL" ]; then \
      mkdir -p /opt/rocm && curl -fsSL "$ROCM_TARBALL" | tar -xzf - -C /opt/rocm; \
      test -x /opt/rocm/llvm/bin/clang++; \
    else \
      /opt/strata/venv/bin/pip install --quiet --disable-pip-version-check \
        --index-url "$ROCM_INDEX" "rocm[libraries,devel]==${ROCM_VERSION}"; \
    fi

RUN git clone -q "$STRATA_REPO" /opt/strata/src \
    && git -C /opt/strata/src checkout -q "$STRATA_REF" \
    && /opt/strata/venv/bin/pip install --quiet --disable-pip-version-check \
       -r /opt/strata/src/requirements.txt

# setup.py's build_engine_hip, without its download of the llama.cpp sources: CMake fetches the
# revision it pins.
RUN set -e; cd /opt/strata/src; \
    if [ -d /opt/rocm/lib ]; then root=/opt/rocm; libs=/opt/rocm; else \
      root=$(/opt/strata/venv/bin/rocm-sdk path --root); \
      libs=$(ls -d /opt/strata/venv/lib/python3*/site-packages/_rocm_sdk_libraries_gfx110X_dgpu); fi; \
    export PATH="/opt/strata/venv/bin:$root/bin:$root/llvm/bin:$PATH" ROCM_PATH="$root" HIP_PATH="$root" \
           HIP_PLATFORM=amd LD_LIBRARY_PATH="$root/lib:$libs/lib"; \
    cmake -S . -B build-hip -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DSTRATA_ENABLE_HIP=ON -DSTRATA_ENABLE_CUDA=OFF -DSTRATA_BUILD_TESTS=OFF \
      -DSTRATA_PREFILL_MMQ=ON -DSTRATA_MMQ_KQUANTS=ON -DCMAKE_HIP_ARCHITECTURES="$GPU_TARGETS" \
      -DCMAKE_HIP_COMPILER="$root/llvm/bin/clang++" -DCMAKE_HIP_COMPILER_ROCM_ROOT="$root" \
      "-DCMAKE_PREFIX_PATH=$root;$libs" \
      "-DCMAKE_HIP_FLAGS=--rocm-path=$root --rocm-device-lib-path=$root/lib/llvm/amdgcn/bitcode"; \
    cmake --build build-hip --target strata -j"$BUILD_JOBS"; \
    mkdir -p engine && cp build-hip/strata engine/strata && rm -rf build-hip

# The image encoder, on the CPU (setup's build_vision_cpu: AMD has no GPU encoder yet). tools/vision
# builds llama.cpp's mtmd at the commit the engine's ggml is pinned to; it reads only the text model's
# vocabulary (vocab_only), so a mmproj (~0.9 GB) is all the RAM it takes.
ARG LLAMA_CPP_COMMIT=3cf03257f219afbe7334045ff7c6a06ac68c627d
RUN set -e; git init -q /opt/strata/llama; cd /opt/strata/llama; \
    git fetch -q --depth 1 https://github.com/ggml-org/llama.cpp.git "$LLAMA_CPP_COMMIT"; git checkout -q FETCH_HEAD; \
    cd /opt/strata/src; export PATH="/opt/strata/venv/bin:$PATH"; \
    cmake -S tools/vision -B build-vision -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DLLAMA_DIR=/opt/strata/llama -DSTRATA_VISION_CUDA=OFF; \
    cmake --build build-vision --target strata-vision -j"$BUILD_JOBS"; \
    cp build-vision/bin/strata-vision engine/strata-vision; rm -rf build-vision /opt/strata/llama

COPY strata-runner.py /opt/strata/strata-runner.py

ENTRYPOINT []
CMD ["/opt/strata/venv/bin/python", "/opt/strata/strata-runner.py", "--help"]
