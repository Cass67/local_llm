# local-llm-runner-rocmfp4
# Project-owned runner image built from the ROCmFPX fork of llama.cpp.
# Adds ROCmFP3/4/6/8 weight quant kernels + MTP self-speculation (--spec-type draft-mtp).
# HIP-only build (no Vulkan) so llama-server doesn't double-book VRAM across
# phantom Vulkan devices — the OOM that plagues the combined ROCm+Vulkan build.
FROM rocm/dev-ubuntu-24.04:6.3 AS build

# Defaults to the fork's main; override with the commit you validated.
ARG LLAMA_CPP_REPO=https://github.com/charlie12345/ROCmFPX.git
ARG LLAMA_CPP_REF=main
ARG AMDGPU_TARGETS=gfx1100
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    cmake \
    git \
    hipblas-dev \
    hipcub-dev \
    libcurl4-openssl-dev \
    pkg-config \
    python3 \
    rocblas-dev \
    && rm -rf /var/lib/apt/lists/*

# init+fetch instead of clone --branch so LLAMA_CPP_REF can be a commit sha
WORKDIR /src/llama.cpp
RUN git init . \
    && git remote add origin "$LLAMA_CPP_REPO" \
    && git fetch --depth 1 origin "$LLAMA_CPP_REF" \
    && git checkout FETCH_HEAD
COPY top-k-hip.patch /tmp/top-k-hip.patch
RUN git apply --check /tmp/top-k-hip.patch \
    && git apply /tmp/top-k-hip.patch
RUN cmake -S . -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_COMPILER=/opt/rocm/llvm/bin/clang \
    -DCMAKE_CXX_COMPILER=/opt/rocm/llvm/bin/clang++ \
    -DLLAMA_CURL=ON \
    -DGGML_HIP=ON \
    -DGGML_HIP_FORCE_MMQ=ON \
    -DGGML_VULKAN=OFF \
    -DCMAKE_HIP_ARCHITECTURES="$AMDGPU_TARGETS" \
    -DGPU_TARGETS="$AMDGPU_TARGETS" \
    -DAMDGPU_TARGETS="$AMDGPU_TARGETS" \
    -DLLAMA_BUILD_SERVER=ON \
    -DLLAMA_BUILD_WEBUI=OFF \
    -DLLAMA_USE_PREBUILT_WEBUI=OFF \
    && cmake --build build --target llama-server llama-quantize llama-perplexity -j"$(nproc)"

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
    && echo "deb [signed-by=/etc/apt/keyrings/rocm.gpg] https://repo.radeon.com/rocm/apt/6.3 noble main" \
        > /etc/apt/sources.list.d/rocm.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        hip-runtime-amd \
        hipblas \
        rocblas \
    && apt-get purge -y gnupg wget \
    && rm -rf /var/lib/apt/lists/* \
    && echo "/opt/rocm/lib" > /etc/ld.so.conf.d/rocm.conf

COPY --from=build /src/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
COPY --from=build /src/llama.cpp/build/bin/llama-quantize /usr/local/bin/llama-quantize
COPY --from=build /src/llama.cpp/build/bin/llama-perplexity /usr/local/bin/llama-perplexity
COPY --from=build /src/llama.cpp/build/bin/*.so /usr/local/lib/
COPY --from=build /opt/rocm-6.3.0/lib/llvm/lib/libomp.so /usr/local/lib/
RUN ldconfig
ENTRYPOINT []
CMD ["llama-server", "--help"]
