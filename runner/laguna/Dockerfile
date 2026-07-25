# local-llm-runner-laguna
# Project-owned runner image built from mainline llama.cpp (ggml-org), which carries
# Laguna model support (LLM_ARCH_LAGUNA) as of release b10087.
# Vulkan backend so it runs on both AMD (radeon ICD) and NVIDIA (nvidia_egl ICD).
# Was previously built from poolside's fork for DFlash speculative decoding; DFlash
# benchmarked net-negative under real sampling and is disabled, so we run stock —
# ~10% faster decode / ~6% faster prefill than the fork on Laguna-S-2.1 IQ2 (2x7900).
FROM ubuntu:24.04 AS build

# Pin a mainline release tag (>= b10087 for laguna arch); can also be a commit sha.
ARG LLAMA_CPP_REF=b10107
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
    && git remote add origin https://github.com/ggml-org/llama.cpp.git \
    && git fetch --depth 1 origin "$LLAMA_CPP_REF" \
    && git checkout FETCH_HEAD
RUN cmake -S . -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DLLAMA_CURL=ON \
    -DGGML_VULKAN=ON \
    -DLLAMA_BUILD_UI=OFF \
    -DLLAMA_USE_PREBUILT_UI=OFF \
    && cmake --build build --target llama-server -j"$(nproc)"

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
COPY --from=build /src/llama.cpp/build/bin/*.so /usr/local/lib/

# Headless NVIDIA Vulkan ICD — uses libEGL_nvidia.so.0 (injected by nvidia-container-toolkit)
# which works without a display, unlike libGLX_nvidia.so.0
RUN mkdir -p /usr/share/vulkan/icd.d && \
    printf '{"file_format_version":"1.0.1","ICD":{"library_path":"libEGL_nvidia.so.0","api_version":"1.4.312"}}' \
    > /usr/share/vulkan/icd.d/nvidia_egl_icd.json

RUN ldconfig
ENTRYPOINT []
CMD ["llama-server", "--help"]
