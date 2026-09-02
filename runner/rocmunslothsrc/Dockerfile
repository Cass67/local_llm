# local-llm-runner-rocmunslothsrc
# unslothai/llama.cpp built FROM SOURCE, by replaying their release recipe.
#
# Their release tags are real git refs pointing at the unsloth master commit that carries
# scripts/unsloth/pr-set.json -- the recipe, not the merged tree. CI checks out an upstream
# base tag and `git merge --no-ff` each pinned PR commit in listed order, then builds. The
# -mix-<hash> suffix is a hash of the PR set, which is why that hash 404s as a commit.
# Replaying it here is deterministic: base tag + 14 commit-pinned PRs, all version controlled.
#
# Why source rather than the vendored tarball (runner/rocmunsloth):
#   * gfx1100 only, instead of their gfx1100;1101;1102;1103;1250 fat binary
#   * updates are a tag bump you can see and review, not an opaque blob swap
#
# Deliberately NO local patches: this is exactly their release recipe and nothing else, so a
# build here is reproducible from version-controlled inputs and comparable to their binaries.
# That means it inherits their base. b10715 was cut 2026-08-31 10:11, two hours and forty-nine
# minutes before upstream f8dbcd61 "ROCm: add radix TOP_K" landed, so llama-server logs
#   llama_sampler_backend_support: device 'ROCm2' does not have support for op TOP_K
# and the sampler falls back to CPU. That resolves itself when their base moves past it; do
# not paper over it here.
FROM rocm/dev-ubuntu-24.04:7.2 AS build

# The unsloth release tag. Its tree pins the base and the PR set; both are read below.
ARG UNSLOTH_TAG=b10715-mix-86bd2d3
ARG UNSLOTH_REPO=https://github.com/unslothai/llama.cpp.git
ARG UPSTREAM_REPO=https://github.com/ggml-org/llama.cpp.git
# Upstream base the tag was cut from (b10715). Kept explicit: the tag name encodes it, but
# parsing a tag name to decide what to build is a worse failure mode than a wrong pin.
ARG UPSTREAM_BASE=662a0b0121a5
ARG AMDGPU_TARGETS=gfx1100
ARG BUILD_JOBS=4
ENV DEBIAN_FRONTEND=noninteractive

RUN for i in 1 2 3 4 5; do \
      apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates cmake curl git hipblas-dev jq \
        libcurl4-openssl-dev rccl-dev pkg-config python3 rocblas-dev \
      && break; \
      echo "apt attempt $i failed, discarding cached debs and retrying"; \
      apt-get clean; dpkg --configure -a || true; \
    done \
    && dpkg -s hipblaslt >/dev/null \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src/llama.cpp
# The recipe is read over HTTP, not with `git show <tag>:<path>`: this is a blob:none clone of
# ggml-org, so git's promisor remote is ggml-org, and pr-set.json's blob exists only in
# unslothai -- the on-demand fetch has nowhere valid to go and the step dies before the loop.
# Replay the recipe: upstream base, then each pinned PR commit merged in listed order.
# Merge order matters for conflicts (their CI says so), so the json order is preserved. Two of
# the fourteen genuinely conflict under a plain merge, which is why their CI falls back to
# scripts/unsloth/additive_merge.py: it resolves ONLY conflicts that are provably pure add/add
# (two PRs registering an architecture at the same spot, where the union is the answer) and
# refuses anything where either side edited shared text, so a real disagreement still hard
# fails. Using their resolver rather than a hand-rolled one keeps this a faithful replay.
# NOTE: no `git fetch --tags unsloth`. It prints the tag list and then exits non-zero, because
# those tags reference commits absent from a --filter=blob:none clone of ggml-org, which killed
# the && chain before the script ever ran and produced a failure with no output. The replay
# fetches each PR commit by sha and reads the recipe over HTTP, so tags are not needed.
COPY replay-mix.sh /usr/local/bin/replay-mix.sh
RUN git clone --filter=blob:none "$UPSTREAM_REPO" . \
    && git checkout "$UPSTREAM_BASE" \
    && git remote add unsloth "$UNSLOTH_REPO" \
    && git config user.email build@local && git config user.name build \
    && replay-mix.sh "$UNSLOTH_TAG" "$UPSTREAM_BASE"

RUN cmake -S . -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_COMPILER=/opt/rocm/llvm/bin/clang \
    -DCMAKE_CXX_COMPILER=/opt/rocm/llvm/bin/clang++ \
    -DLLAMA_CURL=ON -DGGML_HIP=ON -DGGML_HIP_RCCL=ON \
    -DGGML_CUDA_FORCE_MMQ=OFF -DGGML_CUDA_FORCE_CUBLAS=ON \
    -DAMDGPU_TARGETS="$AMDGPU_TARGETS" \
    -DLLAMA_BUILD_UI=ON -DLLAMA_USE_PREBUILT_UI=ON \
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
          hip-runtime-amd hipblas rccl rocblas && break; \
        echo "apt attempt $i failed, discarding cached debs and retrying"; \
        apt-get clean; dpkg --configure -a || true; \
      done \
    && dpkg -s hipblaslt >/dev/null \
    && apt-get purge -y gnupg wget && rm -rf /var/lib/apt/lists/* \
    && echo "/opt/rocm/lib" > /etc/ld.so.conf.d/rocm.conf

COPY --from=build /src/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
COPY --from=build /src/llama.cpp/build/bin/llama-bench /usr/local/bin/llama-bench
COPY --from=build /src/llama.cpp/build/bin/llama-perplexity /usr/local/bin/llama-perplexity
COPY --from=build /src/llama.cpp/build/bin/*.so /usr/local/lib/
COPY --from=build /src/libomp.so /usr/local/lib/
RUN ldconfig
ENTRYPOINT []
CMD ["llama-server", "--help"]
