# local-llm-runner-vulkanqwen4exp
# Vulkan runner built from LaurentZuijdwijk/llama.cpp, branch vulkan/qwen4exp-rocmfpx.
# Testing one hypothesis: that fork's MoE prefill work (tiled concat-transpose,
# f16 B for mul_mat_id, IQ3_S mul_mat_vec spill fix) helps Qwen3.8-Flash-Next, a
# 512-expert MoE, at wide ubatch -- where mainline's scaling flattens out.
# NOT for its headline --spec-draft-adaptive: that is wired only into the
# draft-model impls (simple/eagle3/mtp/dflash), never ngram-mod, which is the
# only speculation Flash-Next can use (no MTP head, no DFlash sidecar).
# Upstream tuning was measured on gfx1151 (Strix Halo APU), not gfx1100.
FROM ubuntu:24.04 AS build

# Tracks master. Known gfx1100 regression window: 788e07dc9 (Jul 17) ->
# 3018a11e7 (Jul 29) cost ~21% prefill and ~12% tg at identical flags, measured
# in docs/benchmarks/2026-07-30-parallel-cont-batching.md. If a rebuild loses
# throughput, re-pin to the good commit to confirm before bisecting:
#   docker build --build-arg LLAMA_CPP_REF=788e07dc91d266ad3162a1ce9037665656269689 ...
ARG LLAMA_CPP_REF=vulkan/qwen4exp-rocmfpx
ARG LLAMA_CPP_REPO=https://github.com/LaurentZuijdwijk/llama.cpp.git
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    cmake \
    git \
    glslang-tools \
    glslc \
    libcurl4-openssl-dev \
    libvulkan-dev \
    pkg-config \
    spirv-headers \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# init+fetch instead of clone --branch so LLAMA_CPP_REF can be a commit sha
WORKDIR /src/llama.cpp
RUN git init . \
    && git remote add origin "$LLAMA_CPP_REPO" \
    && git fetch --depth 1 origin "$LLAMA_CPP_REF" \
    && git checkout FETCH_HEAD
RUN cmake -S . -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DLLAMA_CURL=ON \
    -DGGML_VULKAN=ON \
    -DLLAMA_VULKAN=1 \
    -DLLAMA_BUILD_UI=OFF \
    -DLLAMA_USE_PREBUILT_UI=OFF \
    && cmake --build build --target llama-server llama-bench -j"$(nproc)"

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libcurl4 \
    libgomp1 \
    libvulkan1 \
    libxext6 \
    mesa-vulkan-drivers \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /src/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
COPY --from=build /src/llama.cpp/build/bin/llama-bench /usr/local/bin/llama-bench
COPY --from=build /src/llama.cpp/build/bin/*.so /usr/local/lib/

# Headless NVIDIA Vulkan ICD — uses libEGL_nvidia.so.0 (injected by nvidia-container-toolkit)
# which works without a display, unlike libGLX_nvidia.so.0
RUN mkdir -p /usr/share/vulkan/icd.d && \
    printf '{"file_format_version":"1.0.1","ICD":{"library_path":"libEGL_nvidia.so.0","api_version":"1.4.312"}}' \
    > /usr/share/vulkan/icd.d/nvidia_egl_icd.json

RUN ldconfig
ENTRYPOINT []
CMD ["llama-server", "--help"]
