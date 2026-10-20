# local-llm-runner-maya
# mw00/project-maya: a Strata fork with its own engine for GLM-5.3-Flash (Maya-S24 here), the experts
# tiered across VRAM, pinned RAM and the GGUF on NVMe. Serves a layer split over the 4x 7900 XT.
#
# Same toolchain as runner/strata: TheRock's ROCm 10.0.0 tarball, whose hipBLASLt 1.4.1 (100401) is
# what tools/hip/gfx1100-glm-hipblaslt-100401.txt was tuned on. That table is upstream PR
# mw00/project-maya#292; until it lands MAYA_REF points at the fork branch carrying it.
#
# Not llama-server: the container runs maya-runner.py, which turns mgmt's argv into the JSON config
# serve/server.py reads. See build_maya_args in container/backend/runtime.py.
FROM ubuntu:24.04

ARG MAYA_REPO=https://github.com/Cass67/project-maya.git
ARG MAYA_REF=45995155fc4b3e3a2e280c0cbc6c54f61d314e39
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

# Open upstream PRs measured on this box (2026-10-20, Maya-S24, 4x 7900 XT): #138 cuts a prompt shorter than one
# chunk per card into one chunk per card (MAYA_GLM_PREFILL_SHORT=1; 8K prompt 604 -> 827 tok/s), #199 the prompt's
# KDA recurrence over 4 blocks a head. Drop each when it lands upstream.
COPY patches /opt/maya/patches
RUN cd /opt/maya/src && for p in /opt/maya/patches/*.patch; do git apply "$p"; done

# maya.py's build_engine for HIP (one architecture, no tests)
RUN set -e; cd /opt/maya/src; root=/opt/rocm; \
    export PATH="$root/bin:$root/llvm/bin:$PATH" ROCM_PATH="$root" HIP_PATH="$root" HIP_PLATFORM=amd \
           LD_LIBRARY_PATH="$root/lib"; \
    cmake -S . -B build-hip -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DSTRATA_ENABLE_HIP=ON -DSTRATA_ENABLE_CUDA=OFF -DSTRATA_PREFILL_MMQ=ON \
      -DSTRATA_NATIVE_EXPERTS=ON -DSTRATA_BUILD_TESTS=OFF -DCMAKE_HIP_ARCHITECTURES="$GPU_TARGETS" \
      -DCMAKE_HIP_COMPILER="$root/llvm/bin/clang++" -DCMAKE_PREFIX_PATH="$root" \
      -DSTRATA_GGML_DIR=/opt/maya/src/third_party/llama.cpp \
      "-DCMAKE_HIP_FLAGS=--rocm-path=$root --rocm-device-lib-path=$root/lib/llvm/amdgcn/bitcode"; \
    cmake --build build-hip --target maya -j"$BUILD_JOBS"; \
    mkdir -p engine && cp build-hip/maya engine/maya && rm -rf build-hip

COPY maya-runner.py /opt/maya/maya-runner.py

# The dashboard (http://ubt26:<port>/) defaults its API key to the runner's fixed dummy one, so the chat
# works without entering it under About > Settings; a key entered there still wins.
RUN grep -q 'store.get("apikey", "")' /opt/maya/src/serve/web/app.js \
    && sed -i 's/store.get("apikey", "")/store.get("apikey", "local-llm")/' /opt/maya/src/serve/web/app.js

ENTRYPOINT []
CMD ["/opt/maya/venv/bin/python", "/opt/maya/maya-runner.py", "--help"]
