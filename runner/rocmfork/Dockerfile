# local-llm-runner-rocmfork
# HIP/ROCm build of LaurentZuijdwijk/llama.cpp, branch vulkan/qwen4exp-rocmfpx.
# The fork advertises itself as a Vulkan fork, but --spec-draft-adaptive lives in
# common/speculative.cpp and is backend-agnostic, and the FP4 path has HIP kernels
# (ggml/rocmfp4/rocmfp4_hip.cu). Its Vulkan path is unusable for qwen4exp on gfx1100
# (measured 0.24 t/s decode vs 20.3 on ROCm) though it is healthy on qwen35 27B,
# so HIP is the only way to reach the adaptive-speculation work from here.
FROM rocm/dev-ubuntu-24.04:7.2 AS build

ARG LLAMA_CPP_REF=vulkan/qwen4exp-rocmfpx
ARG LLAMA_CPP_REPO=https://github.com/LaurentZuijdwijk/llama.cpp.git
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
# ggml-cuda compiles CUB out on HIP and then refuses TOP_K above 1024 columns, so the sampler's
# top-k op (the vocab row, ~151k wide) falls back to the CPU backend:
#   llama_sampler_backend_support: device 'ROCm2' does not have support for op TOP_K
#     needed for sampler 'top-k'
# and the logits row round-trips device->host once per token. Upstream fixed it in f8dbcd61
# ("ROCm: add radix TOP_K for long rows", #27466) with an O(N) radix select that handles nrows
# and is HIP-graph capture safe; we vendor that file rather than carry our own kernel. The same
# pair applied cleanly to two unrelated forks already (rocmqwen4exp2, and a 761797ff-based tree),
# so it is not tied to one base. Upstream relaxes ONLY TOP_K -- ARGSORT keeps its 1024 limit,
# because the bitonic argsort kernel is structurally capped near 1024 columns and relaxing it
# aborts at context reserve.
COPY top-k.cu /src/top-k.cu
COPY topk-supports-op.patch /src/topk-supports-op.patch
RUN cp /src/top-k.cu ggml/src/ggml-cuda/top-k.cu \
    && git apply -v /src/topk-supports-op.patch \
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
