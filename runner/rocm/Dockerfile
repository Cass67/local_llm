# local-llm-runner-rocm
# Project-owned llama.cpp runner image, ROCm/HIP backend.
FROM rocm/dev-ubuntu-24.04:6.3 AS build

ARG LLAMA_CPP_REF=master
ARG AMDGPU_TARGETS=gfx1100
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

WORKDIR /src
RUN git clone --depth 1 --branch "$LLAMA_CPP_REF" https://github.com/ggml-org/llama.cpp.git
WORKDIR /src/llama.cpp
RUN cmake -S . -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_COMPILER=/opt/rocm/llvm/bin/clang \
    -DCMAKE_CXX_COMPILER=/opt/rocm/llvm/bin/clang++ \
    -DLLAMA_CURL=ON \
    -DGGML_HIP=ON \
    -DAMDGPU_TARGETS="$AMDGPU_TARGETS" \
    -DLLAMA_BUILD_UI=OFF \
    -DLLAMA_USE_PREBUILT_UI=OFF \
    && cmake --build build --target llama-server -j"$(nproc)"

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
        rocblas \
    && apt-get purge -y gnupg wget \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /src/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
COPY --from=build /src/llama.cpp/build/bin/*.so /usr/local/lib/
RUN ldconfig
ENTRYPOINT []
CMD ["llama-server", "--help"]
