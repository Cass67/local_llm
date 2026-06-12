# local-llm-runner
# Project-owned llama.cpp runner image. local_llm owns container lifecycle and command.
FROM ubuntu:24.04 AS build

ARG LLAMA_CPP_REF=master
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    cmake \
    git \
    libcurl4-openssl-dev \
    libvulkan-dev \
    pkg-config \
    python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --depth 1 --branch "$LLAMA_CPP_REF" https://github.com/ggml-org/llama.cpp.git
WORKDIR /src/llama.cpp
RUN cmake -S . -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DLLAMA_CURL=ON \
    -DGGML_VULKAN=ON \
    -DLLAMA_VULKAN=1 \
    && cmake --build build --target llama-server -j"$(nproc)"

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libcurl4 \
    libgomp1 \
    libvulkan1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /src/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
ENTRYPOINT []
CMD ["llama-server", "--help"]
