# local-llm-runner-laguna
# Project-owned runner image built from poolside's llama.cpp fork, laguna branch.
# Vulkan backend so it runs on both AMD (radeon ICD) and NVIDIA (nvidia_egl ICD).
# Carries Laguna model support + DFlash speculative decoding (--spec-type draft-dflash).
FROM ubuntu:24.04 AS build

# laguna is a branch on the fork; can also be a commit sha on that branch.
ARG LLAMA_CPP_REF=laguna
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
    && git remote add origin https://github.com/poolsideai/llama.cpp.git \
    && git fetch --depth 1 origin "$LLAMA_CPP_REF" \
    && git checkout FETCH_HEAD
# The laguna branch's DFlash code (common/speculative.cpp) calls std::isfinite
# without including <cmath>, which GCC on Ubuntu 24.04 rejects. Force-include it.
RUN cmake -S . -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CXX_FLAGS="-include cmath" \
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
