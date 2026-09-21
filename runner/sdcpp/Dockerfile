# local-llm-sdcpp
# Project-owned stable-diffusion.cpp image, ROCm/HIP backend.
# Serves MiniMax-H3 (video+audio) and Qwen-Image 2.1 (stills) via sd-server.
ARG SDCPP_REF=master

# ── WebUI ────────────────────────────────────────────────────────────────────
# The WebUI ships as an unbuilt Vite app and sd-server's --serve-html-path can
# only serve a single file, so vite-plugin-singlefile's inlined dist/index.html
# is the only usable form. Built on node:22 because package.json needs node>=20.
FROM node:22-slim AS ui
ARG SDCPP_REF
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git init . \
    && git remote add origin https://github.com/leejet/stable-diffusion.cpp.git \
    && git fetch --depth 1 origin "$SDCPP_REF" \
    && git checkout FETCH_HEAD \
    && git submodule update --init --depth 1 examples/server/frontend
WORKDIR /src/examples/server/frontend
RUN corepack enable && pnpm install --frozen-lockfile && pnpm build

# ── sd-server ────────────────────────────────────────────────────────────────
FROM rocm/dev-ubuntu-24.04:7.2
ARG SDCPP_REF
ARG AMDGPU_TARGETS=gfx1100
ENV DEBIAN_FRONTEND=noninteractive

# repo.radeon.com intermittently truncates the large debs; retry instead of failing the build
RUN apt-get update && for i in 1 2 3 4 5; do \
      apt-get install -y --no-install-recommends \
        build-essential ca-certificates cmake ninja-build git \
        hipblas-dev rocblas-dev pkg-config \
      && break || { echo "apt attempt $i failed, retrying"; sleep 15; apt-get clean; }; \
    done && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git init . \
    && git remote add origin https://github.com/leejet/stable-diffusion.cpp.git \
    && git fetch --depth 1 origin "$SDCPP_REF" \
    && git checkout FETCH_HEAD \
    && git submodule update --init --recursive --depth 1

WORKDIR /src/build
RUN cmake .. -G Ninja \
      -DCMAKE_C_COMPILER=/opt/rocm/llvm/bin/clang \
      -DCMAKE_CXX_COMPILER=/opt/rocm/llvm/bin/clang++ \
      -DSD_HIPBLAS=ON \
      -DCMAKE_BUILD_TYPE=Release \
      -DGPU_TARGETS="$AMDGPU_TARGETS" \
      -DAMDGPU_TARGETS="$AMDGPU_TARGETS" \
      -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON \
      -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
 && cmake --build . --config Release -j"$(nproc)"

COPY --from=ui /src/examples/server/frontend/dist/index.html /ui/index.html

# libomp ships in this base image but outside the default linker path
ENV LD_LIBRARY_PATH=/opt/rocm/lib/llvm/lib
ENV PATH="/src/build/bin:${PATH}"
WORKDIR /work
