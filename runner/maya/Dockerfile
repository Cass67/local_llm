# local-llm-runner-maya
# mw00/project-maya: a Strata fork with its own engine for GLM-5.3-Flash (Maya-S24 here), the experts
# tiered across VRAM, pinned RAM and the GGUF on NVMe. Serves a layer split over the 4x 7900 XT. Also builds
# maya-ds4, the engine for DeepSeek-V4.1-Flash (Maya-XS here); maya-runner.py picks one from the profile's args.
#
# Same toolchain as runner/strata: TheRock's ROCm 10.0.0 tarball, whose hipBLASLt 1.4.1 (100401) is
# what tools/hip/gfx1100-glm-hipblaslt-100401.txt was tuned on (#292, in v1.1.19 with #290: the NextN
# split's drafting backup taken at setup - a low MAYA_GLM_RESERVE_MB failed without it).
#
# Not llama-server: the container runs maya-runner.py, which turns mgmt's argv into the JSON config
# serve/server.py reads. See build_maya_args in container/backend/runtime.py.
FROM ubuntu:24.04

ARG MAYA_REPO=https://github.com/mw00/project-maya.git
# v1.1.36
ARG MAYA_REF=f031a23b9682551e744e29d0e9f8d527df49f282
ARG ROCM_TARBALL=https://rocm.nightlies.amd.com/tarball-multi-arch/therock-dist-linux-gfx110X-all-10.0.0a20260730.tar.gz
# the ggml maya.py's setup pins (third_party/llama.cpp)
ARG LLAMA_CPP_COMMIT=3cf03257f219afbe7334045ff7c6a06ac68c627d
ARG GPU_TARGETS=gfx1100
# hipcc peaks several GB per TU; -j$(nproc) OOM-kills the clang backend on this 60 GB box.
ARG BUILD_JOBS=8
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential ca-certificates cmake curl git ninja-build python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/rocm && curl -fsSL "$ROCM_TARBALL" | tar -xzf - -C /opt/rocm \
    && test -x /opt/rocm/llvm/bin/clang++

# setup's Python packages (step 3), in a venv the server runs from
RUN git init -q /opt/maya/src && cd /opt/maya/src \
    && git fetch -q --depth 1 "$MAYA_REPO" "$MAYA_REF" && git checkout -q FETCH_HEAD \
    && python3 -m venv /opt/maya/venv \
    && /opt/maya/venv/bin/pip install --quiet --disable-pip-version-check \
       numpy jinja2 regex pyyaml tqdm requests pillow psutil

RUN set -e; git init -q /opt/maya/src/third_party/llama.cpp; cd /opt/maya/src/third_party/llama.cpp; \
    git fetch -q --depth 1 https://github.com/ggml-org/llama.cpp.git "$LLAMA_CPP_COMMIT"; git checkout -q FETCH_HEAD

# 0002 is local: an answer nobody reads (a phone's locked screen) is kept 30 min, not 5, and the
# web chat reconnects for as long.
# 0006: maya-ds4 --experts N (port of Strata 3dd11c6d): the router's top N of 6, weights renormalised.
# 0007: #476's pull clock on HIP (wall_clock64) and DS4_IQ1S_ROWS.
# 0012: full GLM-5.3 (llama.cpp arch glm-dsa) on the GLM engine - roped MLA, the token indexer (top-k 2048),
# plain residual, NextN MTP, batched prompt path; generated from the glm-dsa-port branch (git diff v1.1.36..).
# The ds4 NUMA (MPOL_LOCAL, needs CapAdd SYS_NICE - runtime.py) and down-act-copy patches landed in v1.1.36 (#562, #561).
COPY patches /opt/maya/patches
RUN cd /opt/maya/src && for p in /opt/maya/patches/*.patch; do git apply "$p"; done

# maya.py's build_engine for HIP (one architecture, no tests): GLM's engine and DeepSeek-V4.1-Flash's (maya-ds4;
# v1.1.23 at least - v1.1.22's stops past 32K tokens on AMD)
RUN set -e; cd /opt/maya/src; root=/opt/rocm; \
    export PATH="$root/bin:$root/llvm/bin:$PATH" ROCM_PATH="$root" HIP_PATH="$root" HIP_PLATFORM=amd \
           LD_LIBRARY_PATH="$root/lib"; \
    cmake -S . -B build-hip -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DSTRATA_ENABLE_HIP=ON -DSTRATA_ENABLE_CUDA=OFF -DSTRATA_PREFILL_MMQ=ON \
      -DSTRATA_NATIVE_EXPERTS=ON -DSTRATA_BUILD_TESTS=OFF -DCMAKE_HIP_ARCHITECTURES="$GPU_TARGETS" \
      -DCMAKE_HIP_COMPILER="$root/llvm/bin/clang++" -DCMAKE_PREFIX_PATH="$root" \
      -DSTRATA_GGML_DIR=/opt/maya/src/third_party/llama.cpp \
      "-DCMAKE_HIP_FLAGS=--rocm-path=$root --rocm-device-lib-path=$root/lib/llvm/amdgcn/bitcode"; \
    cmake --build build-hip --target maya maya-ds4 -j"$BUILD_JOBS"; \
    mkdir -p engine && cp build-hip/maya build-hip/maya-ds4 engine/ && rm -rf build-hip

# The image encoder (docs/AMD_MAYA.md "CPU image encoder on Linux": HIP has no GPU vision path): llama.cpp mtmd
# with Maya's GLM-5.3-Flash patch, CPU only, static. Patched after the engine build so the engine's MMQ sources stay
# stock. Images are on when the profile sets mmproj (+ maya_vision_model, the vocab GGUF).
RUN set -e; cd /opt/maya/src; \
    /opt/maya/venv/bin/python tools/vision/glm5next_patch.py third_party/llama.cpp; \
    cmake -S tools/vision -B build-vision-cpu -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DLLAMA_DIR=/opt/maya/src/third_party/llama.cpp -DSTRATA_VISION_CUDA=OFF; \
    cmake --build build-vision-cpu --target maya-vision -j"$BUILD_JOBS"; \
    cp build-vision-cpu/bin/maya-vision engine/maya-vision && rm -rf build-vision-cpu

COPY maya-runner.py /opt/maya/maya-runner.py

# The dashboard (http://ubt26:<port>/) defaults its API key to the runner's fixed dummy one, so the chat
# works without entering it under About > Settings; a key entered there still wins.
RUN grep -q 'store.get("apikey", "")' /opt/maya/src/serve/web/lib.js \
    && sed -i 's/store.get("apikey", "")/store.get("apikey", "local-llm")/' /opt/maya/src/serve/web/lib.js /opt/maya/src/serve/web/settings.js

# runs as root for /dev/kfd, /dev/dri and CAP_SYS_NICE (mbind)
# nosemgrep
ENTRYPOINT []
# nosemgrep
CMD ["/opt/maya/venv/bin/python", "/opt/maya/maya-runner.py", "--help"]
