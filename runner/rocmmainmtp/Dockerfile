# local-llm-runner-rocmmainmtp
# Upstream llama.cpp master PLUS the two Nathanw1014 commits that add MTP sidecar support.
# This is the only configuration that gets both halves:
#   * from master -- qwen4exp native, 09412af3 indexer head slicing (#28023), 0eadefeb
#     recurrent state rollback (#28123), and 36b10154 (#27941): the -kvu NaN collapse fix,
#     the indexer cache ext.x/ext.y save/restore fix (state_read_meta was dropping mrope ext
#     fields -- 198 of 335692 bytes differed on a round trip), seq_cp and block position
#     keying fixes, and 444 rewritten lines of llama-memory-hybrid-idx.cpp. The profile here
#     exercises all of those: kv_unified, ctx_checkpoints, hybrid indexed memory.
#   * from the fork -- 354390810 "load NextN/MTP draft tensors (sidecar and in-file)" and
#     39817c476 "NextN/MTP draft graph and context". Master's draft-mtp is IN-FILE ONLY and
#     REAP-256/320 carry no NextN, so without these master cannot speculate on these models
#     at all (measured: 20.4 t/s vs 44.1 with the fork).
# Both cherry-picks were verified to apply cleanly onto master before this image existed.
# Note master declares -sm tensor unsupported for qwen4exp (36b10154); use layer split.
# A blobless full clone is used rather than a shallow fetch because cherry-pick needs each
# commit's parent to compute the patch.
FROM rocm/dev-ubuntu-24.04:7.2 AS build

ARG LLAMA_CPP_REF=36b10154383b60eb15baac2c7a40d2a5f784faa7
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

ARG FORK_REPO=https://github.com/Nathanw1014/llama.cpp.git
ARG MTP_COMMITS="354390810 39817c476"

WORKDIR /src/llama.cpp
RUN git clone --filter=blob:none "$LLAMA_CPP_REPO" . \
    && git checkout "$LLAMA_CPP_REF" \
    && git remote add fork "$FORK_REPO" \
    && git fetch fork \
    && git -c user.email=build@local -c user.name=build cherry-pick $MTP_COMMITS \
    && git log --oneline -3

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
