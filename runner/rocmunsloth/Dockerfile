# local-llm-runner-rocmunsloth
# unslothai/llama.cpp prebuilt gfx1100 release, vendored.
#
# This is the ONLY build that does MTP on the REAP quants AND tracks upstream AND supports
# cross-model tensor borrowing. Measured 2026-09-01 on REAP-320 UD-Q2_K_XL with unsloth's
# shared-Q8_0 head at -c 8192, --spec-draft-n-max 2:
#     draft acceptance = 0.79395 (551/694), mean len 2.59, eval 40.93 t/s
# against rocmqwen4exp2's 41.26 t/s at n_max 3 -- same speed, but on a base that carries
# upstream's qwen4exp fixes (#27941 kvu/ext-restore/seq_cp, #28023 indexer slices,
# #28123 recurrent rollback, #28040 O(log n) n-gram history) which the fork predates.
#
# Vendored rather than built from source on purpose. The release is an ephemeral CI merge of
# upstream b10715 with about a dozen PRs (MTP is unslothai#144 `mtp/qwen4exp-nextn`, still
# open; borrowing is a separate `mtp/borrow-target-tensors` branch). That merge commit is not
# in the repo -- `92cedc867` and `86bd2d3` both 404 -- so there is no single ref to build, and
# reconstructing the mix by hand is exactly the kind of "applies cleanly, crashes at runtime"
# trap that killed the master+MTP cherry-pick. This packages the artifact we actually measured.
#
# Consequences of vendoring: no radix TOP_K patch, so the sampler falls back to CPU and logs
#   llama_sampler_backend_support: device 'ROCm2' does not have support for op TOP_K
# (harmless, and irrelevant on tensor split which disables backend sampling anyway). Bump
# UNSLOTH_TAG for a newer release; they publish most days.
FROM ubuntu:24.04

ARG UNSLOTH_TAG=b10715-mix-86bd2d3
ARG UNSLOTH_ASSET=app-b10715-mix-86bd2d3-linux-x64-rocm-gfx110X.tar.gz
ENV DEBIAN_FRONTEND=noninteractive

# The tarball ships its own libamdhip64 / hipblaslt / libLLVM, so no ROCm apt repo is needed --
# only the handful of system libs those link against.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl libgomp1 libcurl4 libnuma1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/unsloth
RUN curl -fsSL -o /tmp/app.tar.gz \
      "https://github.com/unslothai/llama.cpp/releases/download/${UNSLOTH_TAG}/${UNSLOTH_ASSET}" \
    && tar -xzf /tmp/app.tar.gz -C /opt/unsloth \
    && rm /tmp/app.tar.gz \
    && test -x /opt/unsloth/llama-server \
    && test -x /opt/unsloth/llama-perplexity \
    && test -x /opt/unsloth/llama-bench

# The bundled ROCm libs sit alongside the binaries; hipblaslt keeps its Tensile data in a subdir.
ENV LD_LIBRARY_PATH=/opt/unsloth:/opt/unsloth/hipblaslt
RUN printf '/opt/unsloth\n/opt/unsloth/hipblaslt\n' > /etc/ld.so.conf.d/unsloth.conf && ldconfig
RUN for b in llama-server llama-bench llama-perplexity llama-cli; do \
      ln -sf /opt/unsloth/$b /usr/local/bin/$b; done

ENTRYPOINT []
CMD ["llama-server", "--help"]
