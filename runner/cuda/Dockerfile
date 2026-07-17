# local-llm-runner-cuda
# Project-owned llama.cpp runner image, CUDA backend.
FROM nvidia/cuda:12.6.3-devel-ubuntu24.04 AS build

ARG LLAMA_CPP_REF=master
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    cmake \
    git \
    libcurl4-openssl-dev \
    pkg-config \
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
    -DCMAKE_CUDA_ARCHITECTURES=61 \
    -DLLAMA_CURL=ON \
    -DGGML_CUDA=ON \
    -DGGML_CUDA_NO_VMM=ON \
    -DGGML_CUDA_FORCE_MMQ=ON \
    -DLLAMA_BUILD_UI=OFF \
    -DLLAMA_USE_PREBUILT_UI=OFF \
    && cmake --build build --target llama-server -j"$(nproc)"

FROM nvidia/cuda:12.6.3-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libcurl4 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /src/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
COPY --from=build /src/llama.cpp/build/bin/*.so /usr/local/lib/
RUN ldconfig
ENTRYPOINT []
CMD ["llama-server", "--help"]
