# local-llm-runner-rocmmain
# Plain upstream llama.cpp, HIP gfx1100. No fork, no vendored patches.
#
# Exists to answer "why are we on forks at all". As of 2026-09-01 upstream master carries
# everything the fork backends were built for except two flags:
#   * src/models/qwen4exp.cpp is upstream now, so Flash-Next needs no fork to load.
#   * f8dbcd61 "ROCm: add radix TOP_K for long rows" (#27466) is in, so the sampler's top-k
#     no longer falls back to the CPU backend -- nothing to vendor here.
#   * 09412af3 "qwen4exp: sum the indexer heads by slices" (#28023): prompt processing
#     2170 -> 2366 t/s at 55k on their box, and the gain grows with context and ubatch.
#   * 0eadefeb "qwen4exp: support recurrent state rollback" (#28123): without it the context
#     is classified SEQ_RM_TYPE_FULL and the server serialises the whole recurrent state to
#     host memory every speculative round, "which costs more than the drafting saves".
#     Both qwen4exp forks predate this, so their MTP may be paying that tax silently.
# Still fork-only, and the whole reason the other images exist:
#   * --spec-draft-adaptive  (LaurentZuijdwijk, commit ca2616991 -- cherry-picks onto master
#                             with one ~70-line conflict hunk in common/speculative.cpp)
#   * --spec-type draft-mtp  (Nathanw1014 -- 35-file conflict vs master, a real porting job)
# Pinned to a sha rather than the master branch so a rebuild is reproducible.
FROM rocm/dev-ubuntu-24.04:7.2 AS build

ARG LLAMA_CPP_REF=3466812d1f06728effe7c0f3c0671117f461672d
ARG LLAMA_CPP_REPO=https://github.com/ggml-org/llama.cpp.git
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
        build-essential ca-certificates cmake git hipblas-dev \
        libcurl4-openssl-dev rccl-dev pkg-config python3 rocblas-dev \
      && break; \
      echo "apt attempt $i failed, discarding cached debs and retrying"; \
      apt-get clean; dpkg --configure -a || true; \
    done \
    && dpkg -s hipblaslt >/dev/null \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src/llama.cpp
RUN git init . \
    && git remote add origin "$LLAMA_CPP_REPO" \
    && git fetch --depth 1 origin "$LLAMA_CPP_REF" \
    && git checkout FETCH_HEAD

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
RUN cp /opt/rocm/lib/llvm/lib/libomp.so /src/libomp.so

FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates gnupg libcurl4 libgomp1 wget \
    && mkdir -p /etc/apt/keyrings \
    && wget -qO /usr/share/keyrings/rocm.gpg.key https://repo.radeon.com/rocm/rocm.gpg.key \
    && gpg --dearmor -o /etc/apt/keyrings/rocm.gpg /usr/share/keyrings/rocm.gpg.key \
    && echo "deb [signed-by=/etc/apt/keyrings/rocm.gpg] https://repo.radeon.com/rocm/apt/7.2 noble main" \
        > /etc/apt/sources.list.d/rocm.list \
    && for i in 1 2 3 4 5; do \
        apt-get update && apt-get install -y --no-install-recommends \
          hip-runtime-amd hipblas rccl rocblas \
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
