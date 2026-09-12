# local-llm-runner-rocmunslothsrc
# unslothai/llama.cpp's ROCm recipe, rebuilt FROM SOURCE so our patches can go in.
#
# Why this exists: runner/rocmunsloth vendors unsloth's prebuilt tarball, which cannot be
# patched. We need 0008 (the host-buffer pin that fixes the multi-GPU page fault, see
# runner/rocmmainmtp/patches) on a build that keeps unsloth's prefill -- rocmmainmtp is stable
# with 0008 but runs prefill at roughly half unsloth's rate.
#
# The recipe is taken from unslothai/llama.cpp .github/workflows/unsloth-prebuilt-rocm.yml and
# the release body of the tag we run (b10909-mix-bea84f7), which lists every merged PR at an
# exact commit. Two deliberate departures from their CI:
#
#   1. MINIMAL PR SET. Their release merges 13 PRs; we take only unslothai#144 (the qwen4exp
#      NextN/MTP head), which is the one our weights need. The other twelve are other
#      architectures, quant types and unrelated fixes. Fewer merges, less chance of the
#      "applies cleanly, crashes at runtime" failure. We take #137 as well because it is about
#      the qwen4exp PLE table specifically (see UNSLOTH_PRS). If prefill still does not match
#      the prebuilt, the next suspects are #152 (map each contiguous run of a context's
#      tensors) and #157 (cudaMemcpyDefault in the ggml_cuda_cpy 2D fast path).
#
#   2. PINNED ROCm. Their CI resolves "weekly"/"latest" by DATE across all version families,
#      which today lands on 10.1.0a20260822. We pin instead, because ROCm 10 was measured slow
#      on gfx1100 here before (see the rocm10 note) and a silent family jump would confound the
#      prefill comparison this image exists to make. Swap ROCM_VERSION to a 7.15.0a nightly
#      (newest is 7.15.0a20260728) to test the other family -- it is one build arg.
#
# ROCm comes from TheRock nightlies, not repo.radeon.com: that is what unsloth links against,
# and it is self-contained, so the runtime stage copies /opt/rocm from the build stage rather
# than installing ROCm from apt. Mixing a TheRock-built binary with apt ROCm 7.2 at runtime is
# exactly the ABI mismatch this avoids.
FROM ubuntu:24.04 AS build

ARG LLAMA_CPP_TAG=b10909
ARG LLAMA_CPP_REPO=https://github.com/ggml-org/llama.cpp.git
ARG UNSLOTH_REPO=https://github.com/unslothai/llama.cpp.git
# PRs merged from unslothai/llama.cpp, in order. Head commits per the b10909-mix release body:
#   144 MTP for Qwen3.8-Flash-Next                        a9e9c3c   -- our weights need it
#   137 batched readahead for lazily read gather tables   4e1865e   -- see note below
# 137 only bites when the PLE is read lazily from a mapping, i.e. the mmap/paged config, not
# the `-ot per_layer_token_embd=CPU --load-mode none` one where the table is wired in RAM.
# TENSOR_READ_LAZY (upstream #27794) marks that table MADV_RANDOM, which turns OFF kernel
# readahead and costs one synchronous fault per gathered row; their microbenchmark on the
# 26.8 GiB table reads 34.8 us/gather with no advice, 130 us as shipped, 5.6 us with this.
# On qwen4exp that is prompt 198 -> 1397 t/s with lazy on, at the same 42.9 GB peak RSS.
ARG UNSLOTH_PRS="144 137"
ARG ROCM_VERSION=10.1.0a20260822
# Two different names for the same family: the tarball is published per-family with an -all
# suffix, while GPU_TARGETS wants real ISA names. Their CI maps gfx110X to
# "gfx1100;gfx1101;gfx1102;gfx1103"; we build only gfx1100 (7900 XT) to keep the build short.
ARG ROCM_ARCHIVE_TARGET=gfx110X-all
ARG GPU_TARGETS=gfx1100
# hipcc peaks several GB per TU; -j$(nproc) OOM-kills the clang backend on this 60 GB box.
ARG BUILD_JOBS=8
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential ca-certificates ccache cmake curl git jq ninja-build \
      libcurl4-openssl-dev pkg-config python3 \
    && rm -rf /var/lib/apt/lists/*

# Streamed straight into the extraction: the tarball is several GB and we do not want a second
# copy of it in the layer.
RUN mkdir -p /opt/rocm \
    && curl -fsSL "https://rocm.nightlies.amd.com/tarball-multi-arch/therock-dist-linux-${ROCM_ARCHIVE_TARGET}-${ROCM_VERSION}.tar.gz" \
       | tar -xzf - -C /opt/rocm \
    && test -x /opt/rocm/llvm/bin/clang++ \
    && echo "ROCm ${ROCM_VERSION} unpacked"

ENV HIP_PATH=/opt/rocm \
    HIP_PLATFORM=amd \
    HIP_CLANG_PATH=/opt/rocm/llvm/bin \
    HIP_INCLUDE_PATH=/opt/rocm/include \
    HIP_LIB_PATH=/opt/rocm/lib \
    HIP_DEVICE_LIB_PATH=/opt/rocm/lib/llvm/amdgcn/bitcode \
    PATH=/opt/rocm/bin:/opt/rocm/llvm/bin:$PATH

WORKDIR /src/llama.cpp
COPY patches/ /src/patches/

# Not a shallow depth-1 fetch: the PR merge needs a common ancestor, and depth 1 has none.
RUN git init -q . \
    && git remote add origin "$LLAMA_CPP_REPO" \
    && git remote add unsloth "$UNSLOTH_REPO" \
    && git fetch -q --depth 500 origin "refs/tags/${LLAMA_CPP_TAG}:refs/tags/${LLAMA_CPP_TAG}" \
    && git checkout -q "$LLAMA_CPP_TAG" \
    && for pr in $UNSLOTH_PRS; do \
         git fetch -q --depth 500 unsloth "pull/$pr/head:pr$pr" \
         && git -c user.email=build@local -c user.name=build merge --no-edit "pr$pr" \
         || exit 1; \
       done \
    && git -c user.email=build@local -c user.name=build am --keep-non-patch /src/patches/*.patch \
    && git log --oneline -4

# Flags mirror unsloth-prebuilt-rocm.yml. GGML_HIP_ROCWMMA_FATTN stays OFF (rocWMMA costs
# decode on RDNA3 here, independently confirmed); GGML_OPENMP=OFF and GGML_RPC=ON are theirs.
RUN cmake -S . -B build -G Ninja \
      -DCMAKE_C_COMPILER=/opt/rocm/llvm/bin/clang \
      -DCMAKE_CXX_COMPILER=/opt/rocm/llvm/bin/clang++ \
      -DCMAKE_CXX_FLAGS="-I/opt/rocm/include" \
      -DCMAKE_BUILD_TYPE=Release \
      -DGPU_TARGETS="$GPU_TARGETS" \
      -DBUILD_SHARED_LIBS=ON \
      -DGGML_STATIC=OFF \
      -DGGML_NATIVE=OFF \
      -DGGML_HIP=ON \
      -DGGML_OPENMP=OFF \
      -DGGML_RPC=ON \
      -DGGML_CUDA_FORCE_CUBLAS=OFF \
      -DGGML_HIP_ROCWMMA_FATTN=OFF \
      -DLLAMA_BUILD_TESTS=OFF \
      -DLLAMA_CURL=ON \
    && cmake --build build --target llama-server llama-bench llama-perplexity -j"$BUILD_JOBS"

FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates libcurl4 libgomp1 libnuma1 \
    && rm -rf /var/lib/apt/lists/*

# TheRock is self-contained -- no apt ROCm here on purpose (see header).
COPY --from=build /opt/rocm/lib /opt/rocm/lib
COPY --from=build /src/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
COPY --from=build /src/llama.cpp/build/bin/llama-bench /usr/local/bin/llama-bench
COPY --from=build /src/llama.cpp/build/bin/llama-perplexity /usr/local/bin/llama-perplexity
COPY --from=build /src/llama.cpp/build/bin/*.so /usr/local/lib/
RUN printf '/opt/rocm/lib\n/opt/rocm/lib/llvm/lib\n/usr/local/lib\n' > /etc/ld.so.conf.d/rocm.conf \
    && ldconfig

ENTRYPOINT []
CMD ["llama-server", "--help"]
