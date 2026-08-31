# local-llm-runner-rocmqwen4exp3
# Upstream ggml-org/llama.cpp master + the two still-open qwen4exp PRs, replacing the
# Nathanw1014 fork (runner/rocmqwen4exp2). Rationale, measured 2026-08-30:
#   - the fork's headline patch (631b9ffb decode graph reuse) is worth ~0 once MTP is on:
#     LLAMA_GRAPH_REUSE_DISABLE=1 measured 18.53 tok/s vs 17.9-18.2 with reuse at 28.8%.
#   - master already carries #27742 (qwen4exp base) and #27880 (fewer graph splits),
#     which the fork pin does NOT have.
#   - #27836 (NextN/MTP draft head) is still OPEN and is worth +25% here, so plain master
#     is not an option -- it has to be merged in.
#   - #27879 (qwen4exp correctness fixes) is still OPEN and rewrites the same file.
# The merge is done OUT OF TREE and copied in, because the two PRs conflict once:
# both edit the is_ple() tensor block in src/models/qwen4exp.cpp. #27879 fixes the dims
# (n_embd -> ple_dim = ple_head_dim * ple_n_heads); #27836 threads `flags` through so the
# MTP sidecar can mark them skippable. The resolution takes both -- 27879's dims with
# 27836's flags. Rebuild the context with scripts/build-q4e3-src.sh.
FROM rocm/dev-ubuntu-24.04:7.2 AS build

ARG AMDGPU_TARGETS=gfx1100
# hipcc peaks several GB per TU; -j$(nproc) OOM-kills the clang backend on this 60 GB box
ARG BUILD_JOBS=4
ARG GGML_CUDA_FORCE_MMQ=OFF
ARG GGML_CUDA_FORCE_CUBLAS=ON
ENV DEBIAN_FRONTEND=noninteractive

# repo.radeon.com intermittently serves a corrupt hipblaslt deb (1.6 GB, "lzma error:
# compressed data is corrupt"), which fails dpkg unpack at a random Tensile .co file.
# The hash in the Packages index still matches, so apt does not retry on its own.
RUN for i in 1 2 3 4 5; do \
      apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        git \
        hipblas-dev \
        libcurl4-openssl-dev \
        rccl-dev \
        pkg-config \
        python3 \
        rocblas-dev \
      && break; \
      echo "apt attempt $i failed, discarding cached debs and retrying"; \
      apt-get clean; dpkg --configure -a || true; \
    done \
    && dpkg -s hipblaslt >/dev/null \
    && rm -rf /var/lib/apt/lists/*

# the source is a pre-merged tree in the build context, not a git ref -- see the header
WORKDIR /src/llama.cpp
COPY llama.cpp/ /src/llama.cpp/
RUN cmake -S . -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_COMPILER=/opt/rocm/llvm/bin/clang \
    -DCMAKE_CXX_COMPILER=/opt/rocm/llvm/bin/clang++ \
    -DLLAMA_CURL=ON \
    -DGGML_HIP=ON \
    -DGGML_HIP_RCCL=ON \
    -DGGML_CUDA_FORCE_MMQ="$GGML_CUDA_FORCE_MMQ" \
    -DGGML_CUDA_FORCE_CUBLAS="$GGML_CUDA_FORCE_CUBLAS" \
    -DAMDGPU_TARGETS="$AMDGPU_TARGETS" \
    -DLLAMA_BUILD_UI=OFF \
    -DLLAMA_USE_PREBUILT_UI=OFF \
    && cmake --build build --target llama-server llama-bench llama-perplexity -j"$BUILD_JOBS"
# stage libomp via the /opt/rocm symlink so the ROCm patch version isn't hardcoded below
RUN cp /opt/rocm/lib/llvm/lib/libomp.so /src/libomp.so

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gnupg \
    libcurl4 \
    libgomp1 \
    wget \
    && mkdir -p /etc/apt/keyrings \
    && wget -qO /usr/share/keyrings/rocm.gpg.key https://repo.radeon.com/rocm/rocm.gpg.key \
    && gpg --dearmor -o /etc/apt/keyrings/rocm.gpg /usr/share/keyrings/rocm.gpg.key \
    && echo "deb [signed-by=/etc/apt/keyrings/rocm.gpg] https://repo.radeon.com/rocm/apt/7.2 noble main" \
        > /etc/apt/sources.list.d/rocm.list \
    && for i in 1 2 3 4 5; do \
        apt-get update && apt-get install -y --no-install-recommends \
          hip-runtime-amd \
          hipblas \
          rccl \
          rocblas \
        && break; \
        echo "apt attempt $i failed, discarding cached debs and retrying"; \
        apt-get clean; dpkg --configure -a || true; \
      done \
    && dpkg -s hipblaslt >/dev/null \
    && apt-get purge -y gnupg wget \
    && rm -rf /var/lib/apt/lists/* \
    && echo "/opt/rocm/lib" > /etc/ld.so.conf.d/rocm.conf

COPY --from=build /src/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
COPY --from=build /src/llama.cpp/build/bin/llama-bench /usr/local/bin/llama-bench
COPY --from=build /src/llama.cpp/build/bin/llama-perplexity /usr/local/bin/llama-perplexity
COPY --from=build /src/llama.cpp/build/bin/*.so /usr/local/lib/
COPY --from=build /src/libomp.so /usr/local/lib/
RUN ldconfig
ENTRYPOINT []
CMD ["llama-server", "--help"]
