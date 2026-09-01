# local-llm-runner-rocmqwen4exp2
# Same as runner/rocmqwen4exp, but built from Nathanw1014/llama.cpp instead of the
# raw PR. That branch is PR #27742 plus qwen4exp work the PR does not have:
#   631b9ffb  decode graph reuse (llm_graph_input_qsa/_ple never overrode can_reuse,
#             so all ~7000 nodes were rebuilt every token) + host-side PLE gather.
#             +9-11% tg upstream, measured on gfx1151/Vulkan. The fix is CPU-side
#             graph construction, so it should carry to gfx1100/HIP.
#   35439081  NextN/MTP draft tensor loader (sidecar or in-file)
#   39817c47  NextN/MTP draft graph -- --spec-type draft-mtp on Flash-Next, which
#             mainline cannot do at all. Author calls it correctness-only, unbenched.
#   562cb00b  fused QKV segmented for tensor split; 42d97677 finer Q split granularity
#   be71d63c  quantized KV in the QSA attention path
# The branch also carries a large Vulkan stack; none of it compiles in here (GGML_VULKAN off).
# Pinned to the v0.7.1 release source commit rather than the branch tip.
FROM rocm/dev-ubuntu-24.04:7.2 AS build

ARG LLAMA_CPP_REF=39817c476489c37747854bebc29d375770618f1c
ARG LLAMA_CPP_REPO=https://github.com/Nathanw1014/llama.cpp.git
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

# init+fetch instead of clone --branch so LLAMA_CPP_REF can be a commit sha
WORKDIR /src/llama.cpp
RUN git init . \
    && git remote add origin "$LLAMA_CPP_REPO" \
    && git fetch --depth 1 origin "$LLAMA_CPP_REF" \
    && git checkout FETCH_HEAD

# The QSA/DSA indexer calls ggml_top_k() on the full n_kv score vector, but ggml-cuda compiled CUB
# out on HIP and then refused TOP_K above 1024 columns -- so the op fell back to the CPU backend and
# the whole score vector was copied device->host once per QSA layer per token. Measured on 3x
# 7900 XT: 511 graph splits (235 CPU) and 12 CPU round trips per token.
#
# Upstream fixed this properly in f8dbcd61 ("ROCm: add radix TOP_K for long rows", #27466): a real
# O(N) radix select with per-row state, so it handles nrows (prefill) natively and is HIP-graph
# capture safe. We vendor that file rather than carrying our own patch. Note upstream relaxes ONLY
# TOP_K -- ARGSORT keeps its 1024 limit, because the bitonic argsort kernel is structurally capped
# near 1024 columns and relaxing it aborts at context reserve.
COPY top-k.cu /src/top-k.cu
COPY topk-supports-op.patch /src/topk-supports-op.patch
RUN cp /src/top-k.cu ggml/src/ggml-cuda/top-k.cu \
    && git apply /src/topk-supports-op.patch \
    && echo "upstream radix TOP_K (f8dbcd61) applied"
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
    -DLLAMA_BUILD_UI=ON \
    -DLLAMA_USE_PREBUILT_UI=ON \
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
# HIP graph capture costs more than it saves on qwen4exp: 6 paired seeds measured +5.83%
# decode with it off (6/6 wins, identical acceptance), prefill unchanged. The verify batch
# width changes constantly under MTP, so the graph is re-captured continually.
ENV GGML_CUDA_DISABLE_GRAPHS=1

ENTRYPOINT []
CMD ["llama-server", "--help"]
