# local-llm-runner-rocmmainmtp
# Upstream llama.cpp master PLUS unsloth's qwen4exp NextN/MTP series (PR unslothai#144, still
# open) PLUS the LaurentZuijdwijk adaptive-draft commit. Applied as a patch series from
# patches/, not cherry-picked at build time: the two conflicts below are resolved once, here,
# so a rebuild is deterministic instead of racing whatever master looks like today.
#
# Why this replaced the Nathanw1014 cherry-picks that used to live here:
#   Both forks implement a qwen4exp NextN head, but they are DIFFERENT implementations and the
#   sidecar decides which one is correct. unsloth's exporter emits blk.N.nextn.hc_head_{norm,
#   down,up} -- the MTP block's own copy of the hyper-connection mixer, which qwen4exp has in
#   place of a final output norm. Master knows LLM_TENSOR_HC_HEAD_* only as trunk-level
#   "output_hc_*", and the Nathanw1014 loader has no NEXTN_HC_HEAD_* at all, so against an
#   unsloth sidecar it builds the head WITHOUT its output mixer: compiles, loads, generates
#   garbage. Verified by inspecting the sidecar's tensor list against src/llama-arch.cpp.
#   PR #144 adds the mapping, so it is the implementation that matches our weights.
#
# What each patch is for:
#   0001 gguf-py: register NEXTN_HC_HEAD_{NORM,DOWN,UP} + list NextN under QWEN4EXP
#   0002 model:   the NextN/MTP draft head itself                    <-- conflict resolved
#   0003 convert: export the head (--mtp / --no-nextn); unused at runtime, kept for parity
#   0004 llama:   let a draft borrow the target's embd + lm_head (the "shared" sidecar)
#   0005 qwen4exp: allow loading a draft-only MTP export
#   0006 ggml-cuda: key the CUDA graph cache by shape (HIP shares this backend)
#   0007 speculative: --spec-draft-adaptive                          <-- conflict resolved
#
# The two resolutions, both against changes master made after the forks branched:
#   0002 -- master turned n_ff_exp into a per-layer array behind an accessor. The NextN key
#           read MUST come before get_key_or_arr, which sizes n_ff_exp_arr against n_layer_all;
#           and the per-layer read stays the no-arg n_ff_exp(), because n_ff_exp_arr is sized
#           to the trunk and indexing it by il reads past the end for the appended MTP block.
#   0007 -- master added n_max to the common_speculative_impl ctor; the adaptive commit had
#           replaced that ctor to seed its EMA vectors. Merged: master's signature, fork's body.
#
# Sidecar note: use the SELF-CONTAINED head (MTP/mtp-...-Q8_0.gguf, 3.85 GiB, carries its own
# token_embd + output.weight). The "shared" head is 2.6 GiB but only loads via 0004's borrow
# path; the self-contained one needs nothing special and is the safer default.
# Master declares -sm tensor unsupported for qwen4exp; use layer split.
FROM rocm/dev-ubuntu-24.04:7.2 AS build

ARG LLAMA_CPP_REF=050dde50c9d70cf207db84f7224eedc491d817b2
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
COPY patches/ /src/patches/
# A shallow fetch is enough now that nothing is cherry-picked: git am needs only the tip.
RUN git init -q . \
    && git remote add origin "$LLAMA_CPP_REPO" \
    && git fetch -q --depth 1 origin "$LLAMA_CPP_REF" \
    && git checkout -q FETCH_HEAD \
    && git -c user.email=build@local -c user.name=build am --keep-non-patch /src/patches/*.patch \
    && git log --oneline -8

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
