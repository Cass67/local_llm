# local-llm-runner-sglang
# SGLang on gfx1100 (RX 7900 XT). Not a llama.cpp runner -- no llama-server, no
# llama-perplexity, so runner/build.sh does not build this one. Build it directly:
#
#   docker build --network host -t local-llm-runner-sglang:latest runner/sglang
#
# Why this exists: sglang's ROCm support is gfx942/gfx950/gfx1250 only. Upstream
# aborts the kernel build on any other arch and the server cannot start on a box
# without AITER. The four patches here are the minimum that makes it serve on
# RDNA3; each is an open upstream PR or a finding of ours, see patches/ for the
# per-patch rationale.
#
# ROCm 7.2.4 is the default base on purpose. The newer rocm7.14.1 image builds
# and serves fine for 1 GPU and TP=2, but its RCCL 2.30.4 cannot enqueue a
# collective on the card at PCI 13:00.0, so TP=4 dies with
#   HIP failure 'the operation cannot be performed in the present state'
# at rccl enqueue.cc:2061. The llama.cpp runner drives all four of those same
# cards through librccl 1.0.70200 (ROCm 7.2.0), which is what points at the RCCL
# version rather than the hardware. 7.2.4 is also the version sglang itself
# targets -- see the srt_hip_rocm724 extras in python/pyproject_other.toml.
ARG BASE_IMAGE=rocm/pytorch:rocm7.2.4_ubuntu24.04_py3.12_pytorch_release_2.10.0
FROM ${BASE_IMAGE}

ARG SGLANG_REPO=https://github.com/sgl-project/sglang.git
# Pinned: the patches carry exact context, and sgl-kernel moved once already
# (sgl-kernel/ -> python/sglang/kernels/aot/, PR #32648) which silently breaks
# every RDNA PR still open against the old path.
ARG SGLANG_COMMIT=464fffbec8d033de5658447667e7679a20773f2a
ARG GPU_TARGET=gfx1100
# Only needed on a pip-ROCm base (see below); harmless otherwise.
ARG ROCM_DEVEL_INDEX=https://rocm.nightlies.amd.com/v2/gfx110X-all/

ENV DEBIAN_FRONTEND=noninteractive

# Two different base layouts have to work here:
#   classic (7.2.4)  -- a real /opt/rocm with headers, libs and hipcc.
#   pip-ROCm (7.14.1) -- no /opt/rocm at all; ROCm is wheels under
#     site-packages/_rocm_sdk_*, the runtime wheel carries no headers, and the
#     linker cannot see libamdhip64/libhiprtc. rocm-sdk-devel supplies both.
#     --no-deps is mandatory: its dependency closure downgrades rocm-sdk-core to
#     a nightly and torch then dies with "Could not find rocm library 'hipblas'".
# Either way we end at a usable /opt/rocm, so every later step is layout-agnostic
# (sglang's JIT path also hardcodes /opt/rocm/bin/hipcc, so the symlink is load
# bearing, not cosmetic).
RUN if [ ! -x /opt/rocm/bin/hipcc ]; then \
      echo "pip-ROCm base: installing devel tree" \
      && pip install --no-deps --index-url "${ROCM_DEVEL_INDEX}" rocm-sdk-devel \
      && rocm-sdk init \
      && ln -sfn /opt/venv/lib/python3.12/site-packages/_rocm_sdk_devel /opt/rocm; \
    else echo "classic /opt/rocm base"; fi \
    && test -x /opt/rocm/bin/hipcc \
    && test -f /opt/rocm/include/thrust/complex.h \
    && python -c "import torch; assert torch.version.hip, 'torch lost its HIP build'; \
al = torch.cuda.get_arch_list(); \
assert not al or '${GPU_TARGET}' in al, f'base torch has no ${GPU_TARGET}: {al}'; \
print('arch_list:', al or '(empty -- no GPU visible at build time)')"

# RCCL, rebuilt with -DNDEBUG. Stock librccl carries two live device asserts
# (src/device/prims_simple.h:789, src/device/msccl_kernel_impl.h:31) and its
# Release build never defines NDEBUG at all -- `grep -c NDEBUG build.ninja` is 0
# on a stock configure. A device assert pulls in hostcall, hostcall needs PCIe
# atomics, and a GPU whose root port has no AtomicOpsCap then cannot dispatch
# ncclDevKernel_* at all: every collective containing that card dies with
# "AQL dispatch failed" / hipErrorIllegalState. Nobody on datacenter cards ever
# hits this. Costs ~25 min: the device link is a single-threaded lld pass.
ARG RCCL_BRANCH=rocm-7.2.4
RUN pip install --no-cache-dir cmake CppHeaderParser \
    && git clone --depth 1 --branch "${RCCL_BRANCH}" https://github.com/ROCm/rccl.git /tmp/rccl \
    && cmake -S /tmp/rccl -B /opt/rccl/build -G Ninja \
       -DCMAKE_BUILD_TYPE=Release \
       -DCMAKE_PREFIX_PATH=/opt/rocm \
       -DCMAKE_CXX_COMPILER=/opt/rocm/bin/hipcc \
       -DGPU_TARGETS="${GPU_TARGET}" \
       -DBUILD_TESTS=OFF \
       -DCMAKE_CXX_FLAGS=-DNDEBUG \
    && grep -q NDEBUG /opt/rccl/build/build.ninja \
    && cmake --build /opt/rccl/build -j 12 \
    && test -f /opt/rccl/build/librccl.so.1 \
    && rm -rf /tmp/rccl

WORKDIR /opt
RUN git clone "${SGLANG_REPO}" sglang \
    && cd sglang \
    && git checkout "${SGLANG_COMMIT}"

WORKDIR /opt/sglang
COPY patches/ /opt/patches/
# -F3 not plain `git apply`: 0002/0003 are upstream PRs cut against an older
# tree and land at an offset. A hunk that stops applying is a real signal that
# the pin moved -- fix the patch, do not raise the fuzz.
RUN for p in /opt/patches/*.patch; do \
      echo "applying $p" && patch -p1 -F3 --no-backup-if-mismatch < "$p" || exit 1; \
    done

RUN cd python/sglang/kernels/aot \
    && cp -f pyproject_rocm.toml pyproject.toml \
    && CPATH=/opt/rocm/include \
       LDFLAGS="-L/opt/rocm/lib" \
       AMDGPU_TARGET="${GPU_TARGET}" \
       PYTORCH_ROCM_ARCH="${GPU_TARGET}" \
       MAX_JOBS=8 \
       python setup_rocm.py bdist_wheel \
    && pip install --no-deps dist/*.whl \
    && python -c "import sgl_kernel; import torch; \
assert not hasattr(torch.ops.sgl_kernel, 'init_custom_ar'), \
'CDNA all-reduce leaked into the RDNA build'"

# Constraints pin torch/triton: the srt_hip extras would otherwise pull a PyPI
# CUDA torch over the ROCm one. Plain srt_hip, not srt_hip_rocm724 -- the latter
# pins torch==2.11.0 exactly, which no 7.2.4 image ships.
# SGLANG_BUILD_RUST_EXTS=none skips the Rust router, which needs cargo.
RUN cp -f python/pyproject_other.toml python/pyproject.toml \
    && pip list --format=freeze | grep -E '^(torch|torchvision|torchaudio|triton)' > /tmp/constraints.txt \
    && SGLANG_BUILD_RUST_EXTS=none pip install -c /tmp/constraints.txt -e "python[srt_hip]"

# There is no env var for the attention backend, so every launch must pass
# --attention-backend triton by hand: the default maps every HIP device to
# AITER, which is CDNA-only and hard-asserts on RDNA. Upstream #31259 would
# make Triton the RDNA default; it is not carried here because it changes
# behaviour on archs we cannot test.
#
# Multi-GPU also needs --shm-size 1g or larger on the container, same as the
# llama.cpp runners.
ENV HF_HOME=/models/.hf

EXPOSE 30000
ENTRYPOINT []
CMD ["python", "-m", "sglang.launch_server", "--help"]
