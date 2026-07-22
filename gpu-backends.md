# GPU Backends: Requirements, Wiring, and Troubleshooting

This document covers everything needed to run local_llm with any GPU backend.
Read this before touching a Dockerfile, cluster config, or Docker runtime setup.

---

## Table of Contents

1. [Architecture overview](#architecture-overview)
2. [Backend comparison](#backend-comparison)
3. [ROCm / AMD](#rocm--amd)
4. [CUDA / NVIDIA](#cuda--nvidia)
5. [Vulkan / AMD (or NVIDIA headless)](#vulkan)
6. [Mixed AMD + NVIDIA Vulkan](#mixed-amd--nvidia-vulkan)
7. [How the stack wires GPU access at launch](#how-the-stack-wires-gpu-access-at-launch)
8. [Cluster definition and device indexing](#cluster-definition-and-device-indexing)
9. [Troubleshooting](#troubleshooting)

---

## Architecture overview

The management container (`local-llm-mgmt`) never runs llama-server directly.
It spawns a separate runner container per cluster via the Docker socket.
The runner container is built for a specific backend (rocm, cuda, or vulkan)
and receives GPU access through Docker device passthrough or the NVIDIA container runtime.

```
host OS
  ├── /dev/kfd, /dev/dri          ← AMD devices
  ├── /dev/nvidia0, /dev/nvidiactl ← NVIDIA devices (kernel module)
  ├── nvidia-container-runtime     ← injects NVIDIA libs into containers
  └── docker.sock

local-llm-mgmt container (management + API + UI)
  └── spawns → local-llm-runner-{rocm,cuda,vulkan} container
                  └── llama-server (the actual inference process)
```

The management container needs Docker socket access to create/destroy runner containers.
The runner containers need GPU device access injected at container start time.

---

## Backend comparison

| Backend | GPU vendor | Host kernel module | Docker access method | Device env var |
|---------|-----------|-------------------|---------------------|----------------|
| `rocm`         | AMD            | `amdgpu` + `nvidia` | `/dev/kfd`, `/dev/dri` bind-mount + `render` group | `HIP_VISIBLE_DEVICES` |
| `cuda`         | NVIDIA         | `nvidia`            | `nvidia` Docker runtime + `DeviceRequests` | `CUDA_VISIBLE_DEVICES` |
| `vulkan`       | AMD            | `amdgpu`            | `/dev/kfd`, `/dev/dri` bind-mount + `render` group | `GGML_VK_VISIBLE_DEVICES` |
| `vulkan`       | NVIDIA         | `nvidia`            | `nvidia` Docker runtime + graphics capability | `GGML_VK_VISIBLE_DEVICES` |
| `mixed_vulkan` | AMD + NVIDIA   | `amdgpu` + `nvidia` | Both AMD bind-mount and `nvidia` Docker runtime + host graphics lib bind-mounts | `GGML_VK_VISIBLE_DEVICES` |

NVIDIA Vulkan is a special case: same `vulkan` backend in cluster config, but detected
at runtime and wired differently (see [NVIDIA Vulkan](#nvidia-on-vulkan-backend) below).

`mixed_vulkan` is for clusters that span both AMD and NVIDIA GPUs in a single container.
See [Mixed AMD + NVIDIA Vulkan](#mixed-amd--nvidia-vulkan) for the full setup.

---

## ROCm / AMD

### Host requirements

1. **AMDGPU kernel module loaded** — ships with Ubuntu 22.04+ kernels for RDNA2+.
   Verify: `lsmod | grep amdgpu`

2. **ROCm userspace stack installed** — provides `libhip`, `librocblas`, `rocminfo`, etc.
   The Docker image bundles the runtime libraries; the host only needs it for
   `rocminfo` (used by GPU inventory detection).
   Install: [ROCm install guide](https://rocm.docs.amd.com/en/latest/deploy/linux/index.html)
   Verify: `rocminfo | grep -A3 'Agent [0-9]'`

3. **`/dev/kfd` exists with correct group** — kernel fusion driver, the HIP entry point.
   Verify: `ls -l /dev/kfd` → should be `crw-rw---- ... render` (GID 991 on most distros)

4. **`/dev/dri/renderD*` exists** — DRM render nodes, one per GPU.
   Verify: `ls /dev/dri/`

5. **User is in the `render` group** — for management container to access GPU devices.
   Add: `sudo usermod -aG render $USER`
   The render group GID (default 991) must match `RENDER_GROUP` in `.env`.

### Container requirements

The `local-llm-runner-rocm:latest` image:
- Built `FROM rocm/dev-ubuntu-24.04:6.3` (build stage) — includes full ROCm toolchain
- Runtime stage: `ubuntu:24.04` + `hip-runtime-amd`, `hipblas`, `rocblas` from the AMD ROCm apt repo
- No host libraries are injected — everything is self-contained in the image
- `libomp.so` is copied from the build stage because it's not in the apt packages

### Docker access wiring

```python
# runtime.py — ROCm / AMD Vulkan path
devices = ["/dev/kfd", "/dev/dri"]
group_add = [render_group]          # GID 991 by default
environment["HIP_VISIBLE_DEVICES"] = visible_devices   # e.g. "0,1"
# or for vulkan backend:
environment["GGML_VK_VISIBLE_DEVICES"] = visible_devices
```

The management container itself also needs `/dev/kfd` and `/dev/dri` access
(declared in `docker-compose.yml`) so it can run `rocminfo` and `vulkaninfo`
for GPU inventory detection.

### Build

```bash
./runner/build.sh rocm
# Optionally target a specific GPU architecture:
docker build --build-arg AMDGPU_TARGETS=gfx1100 -t local-llm-runner-rocm:latest runner/rocm
```

`AMDGPU_TARGETS` controls which GPU ISA is compiled. Default is `gfx1100` (RDNA3, RX 7900).
For other cards:
- RX 6000 series (RDNA2): `gfx1030`
- RX 5000 series (RDNA): `gfx1010`
- Multiple targets: `gfx1100;gfx1030`

---

## CUDA / NVIDIA

### Host requirements

1. **NVIDIA kernel module** — `nvidia`, `nvidia_drm`, `nvidia_modeset`.
   Verify: `lsmod | grep ^nvidia`

2. **`nvidia-smi` works** — verifies driver + kernel module are matched.
   Verify: `nvidia-smi` — shows GPU table.

3. **NVIDIA Container Toolkit installed and configured** — this is what allows
   Docker containers to access NVIDIA GPUs. Without it, `--runtime=nvidia` does nothing.

   Install (Ubuntu):
   ```bash
   curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
   curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
     sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
     sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
   sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
   sudo nvidia-ctk runtime configure --runtime=docker
   sudo systemctl restart docker
   ```

   Verify: `docker info | grep -i runtime` — should show `nvidia` in the list.

4. **Docker daemon configured with nvidia runtime** — `/etc/docker/daemon.json` must
   declare the nvidia runtime:
   ```json
   {
     "runtimes": {
       "nvidia": {
         "path": "nvidia-container-runtime",
         "args": []
       }
     }
   }
   ```
   The `nvidia-ctk runtime configure` command writes this automatically.

### What nvidia-container-toolkit does

When a container is started with `DeviceRequests: [{"Driver": "nvidia", ...}]`,
the NVIDIA container runtime:
- Binds `/dev/nvidia0`, `/dev/nvidiactl`, `/dev/nvidia-uvm`, etc. into the container
- Injects NVIDIA userspace libraries (libcuda, libcublas, etc.) from the host
  into the container's library path — matching the host driver version
- Does NOT inject Vulkan ICDs (important — see below)

The injected libraries live under `/lib/x86_64-linux-gnu/` inside the container.

### Container requirements

The `local-llm-runner-cuda:latest` image:
- Built `FROM nvidia/cuda:12.6.3-devel-ubuntu24.04` — provides CUDA headers and libraries for build
- Runtime stage: `FROM nvidia/cuda:12.6.3-runtime-ubuntu24.04` — minimal CUDA runtime
- The runtime base image version **must be ≤ the installed driver version** on the host.
  CUDA 12.6.3 requires driver ≥ 560.28.03.
  If the host driver is older, lower the CUDA base version in the Dockerfile.

  Driver → minimum CUDA version table:
  | Driver | Max CUDA |
  |--------|---------|
  | 580.x  | 12.9    |
  | 560.x  | 12.6    |
  | 545.x  | 12.3    |
  | 525.x  | 12.0    |

- Built with `CMAKE_CUDA_ARCHITECTURES=61` for Pascal (P40, P100).
  For other architectures, change this value:
  | GPU family | Architecture | Value |
  |-----------|-------------|-------|
  | P40, P100 | Pascal  | `61`  |
  | V100      | Volta   | `70`  |
  | A100      | Ampere  | `80`  |
  | 3090, 4090| Ampere/Ada | `86` or `89` |

- `GGML_CUDA_NO_VMM=ON` and `GGML_CUDA_FORCE_MMQ=ON` are set for Pascal compatibility.
  Pascal does not support virtual memory management (VMM) or tensor cores,
  so these flags disable the paths that would crash or silently fall back.

### Docker access wiring

```python
# runtime.py — CUDA path
device_requests = [{"Driver": "nvidia", "Count": -1, "Capabilities": [["gpu"]]}]
environment["CUDA_VISIBLE_DEVICES"] = visible_devices   # e.g. "0"
```

`Count: -1` means "all GPUs" at the Docker API level; `CUDA_VISIBLE_DEVICES` then restricts
which GPU the process actually uses. This is intentional: injecting all then filtering
is more reliable than injecting by index, which is fragile when the order changes.

---

## Vulkan

Vulkan is a cross-vendor graphics/compute API. llama-server uses it as a
compute backend via `ggml-vulkan`. It works on AMD (via Mesa RADV driver) and
NVIDIA (via proprietary Vulkan ICD).

### AMD on Vulkan backend

Identical host and container access requirements to ROCm (same `/dev/kfd`, `/dev/dri`
bind-mount, same render group). The difference is only in which library is used
inside the container (Mesa Vulkan RADV drivers instead of ROCm HIP).

```python
# runtime.py — AMD Vulkan path (same as ROCm devices, different env var)
devices = ["/dev/kfd", "/dev/dri"]
group_add = [render_group]
environment["GGML_VK_VISIBLE_DEVICES"] = visible_devices
```

The Vulkan image includes `mesa-vulkan-drivers` which provides RADV (AMD Vulkan).

### NVIDIA on Vulkan backend

NVIDIA GPUs can run the Vulkan backend when CUDA is unavailable or undesirable
(e.g. older host drivers that don't support the required CUDA version, or
simply preferring a lighter runtime).

The cluster `backend` field is still `vulkan`. At launch time, `active_runners.py`
detects NVIDIA GPUs in the cluster's PCI ID list and sets `cfg["nvidia_vulkan"] = True`,
which triggers different Docker wiring in `runtime.py`.

**The NVIDIA Vulkan ICD problem:**

NVIDIA ships two Vulkan ICDs:
- `libGLX_nvidia.so.0` — the GLX (X11) ICD. Requires a display connection.
  `vkCreateInstance` returns NULL headlessly. **Do not use this in containers.**
- `libEGL_nvidia.so.0` — the EGL ICD. Works fully headlessly. **Use this.**

The nvidia-container-toolkit injects both libraries into the container, but only
places `libGLX_nvidia.so.0` in the Vulkan loader's ICD search path via
the `nvidia_icd.json` on the host. This means the default NVIDIA Vulkan setup
in a headless container **does not work** — the device list will be empty.

**The fix baked into the Vulkan Dockerfile:**

The image bakes in a custom ICD JSON file that points at the EGL ICD:

```dockerfile
RUN mkdir -p /usr/share/vulkan/icd.d && \
    printf '{"file_format_version":"1.0.1","ICD":{"library_path":"libEGL_nvidia.so.0","api_version":"1.4.312"}}' \
    > /usr/share/vulkan/icd.d/nvidia_egl_icd.json
```

At launch, `runtime.py` sets `VK_ICD_FILENAMES` to this file, bypassing the
mesa ICDs entirely so the Vulkan loader uses only the NVIDIA EGL ICD:

```python
environment["VK_ICD_FILENAMES"] = "/usr/share/vulkan/icd.d/nvidia_egl_icd.json"
```

This is why the Vulkan Dockerfile does NOT include `libx11-6` or `libxext6` —
EGL doesn't need X11.

**Docker access wiring for NVIDIA Vulkan:**

```python
# runtime.py — NVIDIA Vulkan path
device_requests = [{"Driver": "nvidia", "Count": -1, "Capabilities": [["gpu", "graphics", "compute", "utility"]]}]
environment["VK_ICD_FILENAMES"] = "/usr/share/vulkan/icd.d/nvidia_egl_icd.json"
environment["GGML_VK_VISIBLE_DEVICES"] = "0"   # always 0 — only one GPU injected
```

`compute` is mandatory. Without it the nvidia runtime omits `libnvidia-gpucomp.so`,
the Vulkan ICD fails to init (`vkCreateInstance: Found no drivers!`), llama.cpp logs
`no usable GPU found`, and the model runs on CPU with 0 VRAM used — no hard error.

Note: `GGML_VK_VISIBLE_DEVICES` is always `"0"` for NVIDIA Vulkan because
`visible_devices_for()` returns the host Vulkan index (which might be e.g. `2`),
but only the target GPU's devices are injected into the container — so inside
the container it is always index 0.

**Capability flags**: The `graphics` capability is required for Vulkan on NVIDIA.
CUDA only needs `gpu`. Without `graphics` in the capability list, the NVIDIA
runtime does not inject the graphics libraries (including `libEGL_nvidia.so.0`).

### Host requirements for NVIDIA Vulkan

Same as [CUDA host requirements](#host-requirements-1) — the NVIDIA kernel module
and nvidia-container-toolkit must be installed and configured. Additionally:

- `vulkaninfo` installed on the host (for GPU inventory detection):
  `sudo apt install vulkan-tools`

### Container requirements

`local-llm-runner-vulkan:latest`:
- Runtime base: `ubuntu:24.04` (plain, no NVIDIA base needed — runtime injects libs)
- `libvulkan1` — Vulkan loader (finds and dispatches to ICDs)
- `mesa-vulkan-drivers` — RADV for AMD; ignored on NVIDIA (loader uses VK_ICD_FILENAMES)
- `nvidia_egl_icd.json` baked in at `/usr/share/vulkan/icd.d/`
- llama-server built with `-DGGML_VULKAN=ON`

---

## Mixed AMD + NVIDIA Vulkan

`mixed_vulkan` allows a single cluster to span AMD and NVIDIA GPUs simultaneously,
with all cards visible to a single llama-server process via Vulkan. This is useful
for large models where you want to pool VRAM across different GPU vendors.

**Reference hardware**: AMD RX 7900 XT × 2 (20 GB each) + NVIDIA Tesla P40 (22 GB)
running a Q6_K 40B model split `1:1:1` across all three.

### How it works

The container must satisfy both AMD and NVIDIA access simultaneously:

- **AMD**: `/dev/kfd` + `/dev/dri` bind-mount + render group (same as regular Vulkan)
- **NVIDIA**: `DeviceRequests` with `gpu+graphics+compute+utility` capabilities (same as NVIDIA Vulkan)
- **NVIDIA Vulkan graphics libs**: `libnvidia-gpucomp.so` (needed by the Vulkan ICD) is only
  injected when `compute` is in the capabilities list — `graphics` alone is not enough. The
  pure NVIDIA Vulkan path fixes this by adding `compute`. This mixed path instead bind-mounts
  the support libs (`libnvidia-glcore`, `libnvidia-gpucomp`, `libnvidia-glvkspirv`, etc.) from
  the host, since it already mounts host libs for the AMD side.
- **ICD selection**: `VK_ICD_FILENAMES` explicitly lists both the NVIDIA EGL ICD
  (baked into the image) and the AMD RADV ICD, so the Vulkan loader enumerates
  all cards in one pass.

### Host requirements

All requirements from both [ROCm / AMD](#rocm--amd) and [CUDA / NVIDIA](#cuda--nvidia)
must be met:

1. AMDGPU kernel module loaded — `lsmod | grep amdgpu`
2. NVIDIA kernel module loaded — `lsmod | grep ^nvidia`
3. NVIDIA container toolkit installed and configured — `docker info | grep nvidia`
4. `/dev/kfd` exists with render group, user in render group
5. `/dev/nvidia-modeset` exists — required for NVIDIA Vulkan ICD initialization:
   `ls /dev/nvidia-modeset`
6. NVIDIA graphics libs present in `/usr/lib/x86_64-linux-gnu/`:
   `ls /usr/lib/x86_64-linux-gnu/libnvidia-gpucomp*` — should show the versioned `.so`

### Management container requirements

The mgmt container needs `/usr/lib/x86_64-linux-gnu` from the host mounted read-only
so it can glob for the NVIDIA graphics libs to bind-mount into each runner.
This is declared in `docker-compose.yml`:

```yaml
volumes:
  - /usr/lib/x86_64-linux-gnu:/host/nvidia-libs:ro
```

Without this mount, `runtime.py`'s glob finds nothing and the runner launches without
the NVIDIA graphics libs — `libEGL_nvidia.so.0` will fail `vkCreateInstance` silently
and the P40 (or other NVIDIA GPU) will not appear in `--list-devices`.

### Cluster definition

```json
{
  "id": "dd886af6",
  "name": "7900P40",
  "gpu_pci_ids": [
    "0000:01:00.0",
    "0000:04:00.0",
    "0000:07:00.0"
  ],
  "backend": "mixed_vulkan",
  "port": 8087,
  "container_name": "local-llm-runner-cluster-7900P40-dd886af6"
}
```

`gpu_pci_ids` must list all cards (AMD and NVIDIA). The `visible_devices_for()`
function in `clusters.py` handles `mixed_vulkan` specially: it places NVIDIA cards
first (to match the order the Vulkan loader enumerates them — NVIDIA ICD is listed
first in `VK_ICD_FILENAMES`), then AMD cards. The result is a contiguous range
`"0,1,2"` regardless of how many of each vendor.

### Profile configuration

For a 3-GPU split, use `tensor_split: "1,1,1"` with `visible_devices: "0,1,2"`:

```json
{
  "backend": "mixed_vulkan",
  "ngl": 999,
  "tensor_split": "1,1,1",
  "visible_devices": "0,1,2",
  "split_mode": "row"
}
```

Adjust the tensor split weights if your GPUs have very different VRAM capacities.
Equal weights (`1,1,1`) let llama.cpp distribute proportionally.

### Docker access wiring

```python
# runtime.py — mixed_vulkan path
devices = ["/dev/kfd", "/dev/dri", "/dev/nvidia-modeset"]
group_add = [render_group]
device_requests = [{"Driver": "nvidia", "Count": -1, "Capabilities": [["gpu", "graphics", "utility"]]}]
# glob NVIDIA graphics libs from the host mount, bind them into the runner
_nvidia_libs = glob("/host/nvidia-libs/libGLX_nvidia.so.*", "libnvidia-glcore.so.*", ...)
binds = [f"/usr/lib/x86_64-linux-gnu/{name}:/usr/lib/x86_64-linux-gnu/{name}:ro" for ...]
environment["VK_ICD_FILENAMES"] = (
    "/usr/share/vulkan/icd.d/nvidia_egl_icd.json"
    ":/usr/share/vulkan/icd.d/radeon_icd.json"
)
environment["GGML_VK_VISIBLE_DEVICES"] = "0,1,2"
```

### Container image

Same image as regular Vulkan — `local-llm-runner-vulkan:latest`. The image
already bakes in `nvidia_egl_icd.json` (the headless NVIDIA Vulkan ICD) and
includes `mesa-vulkan-drivers` for AMD RADV.

### Verifying the setup

Confirm all GPUs enumerate inside the running container:

```bash
docker exec <container_name> sh -c 'unset GGML_VK_VISIBLE_DEVICES; /usr/local/bin/llama-server --list-devices'
```

Expected output (order may vary by ICD enumeration):
```
Available devices:
  Vulkan0: AMD Radeon RX 7900 XT (RADV NAVI31) (20464 MiB, ...)
  Vulkan1: Tesla P40 (23040 MiB, ...)
  Vulkan2: AMD Radeon RX 7900 XT (RADV NAVI31) (20464 MiB, ...)
```

If the P40 is missing, see [Mixed Vulkan: P40 not visible](#mixed-vulkan-p40-or-nvidia-gpu-not-visible).

---

## How the stack wires GPU access at launch

This is the sequence from "user clicks Load" to GPU access inside the container.

1. **`active_runners.py: _build_launch_metadata()`**
   - Reads cluster definition (from `STATE_DIR/runs/clusters/`)
   - Calls `detect_gpus()` to get live GPU inventory (PCI IDs, vendor, indices)
   - If cluster backend is `vulkan` and any cluster GPU has `vendor == "nvidia"`:
     sets `cfg["nvidia_vulkan"] = True`
   - Calls `visible_devices_for(cluster, inventory)` → returns backend-appropriate index string
   - For NVIDIA Vulkan: overrides visible_devices to `"0"` (container-internal index)

2. **`runtime.py: _build_container_spec()`**
   - Reads `cfg["backend"]` and `cfg["nvidia_vulkan"]` to choose Docker access method
   - Builds `devices`, `device_requests`, `group_add`, and `environment`
   - Returns `DockerContainerSpec`

3. **`runtime.py: DockerRunner.launch()`**
   - POSTs to Docker API to create and start the container
   - For NVIDIA: Docker runtime intercepts via `nvidia-container-runtime`, injects libs
   - For AMD: kernel bind-mounts `/dev/kfd` and `/dev/dri` directly

4. **`active_runners.py: _wait_ready()`**
   - Polls `GET /v1/models` on the runner's port until 200 or timeout

---

## Cluster definition and device indexing

Clusters are stored in `STATE_DIR/runs/clusters/*.json`:

```json
{
  "id": "4319b958",
  "name": "p40v",
  "gpu_pci_ids": ["0000:01:00.0"],
  "backend": "vulkan",
  "port": 8081,
  "container_name": "local-llm-runner-cluster-p40v"
}
```

`gpu_pci_ids` uses the full PCI address from `lspci -D` (domain:bus:slot.function).
Get it: `lspci -D | grep -i vga`

**GPU index resolution** (`clusters.py: visible_devices_for()`):

| Backend | Index source | Command |
|---------|-------------|---------|
| `rocm`  | `rocminfo` agent index (0-based GPU agents) | `rocminfo` |
| `cuda`  | `nvidia-smi` index | `nvidia-smi --query-gpu=index,pci.bus_id --format=csv` |
| `vulkan`| `vulkaninfo --summary` device order | `vulkaninfo --summary` |

The management container runs these commands at launch time to map PCI IDs to runtime indices.

**Backend validation**: `rocm` and `cuda` backends require all cluster GPUs to be
the matching vendor (AMD / NVIDIA respectively). `vulkan` accepts either.

---

## Troubleshooting

### P40 / NVIDIA Vulkan: "Available devices:" empty

Check in order:

1. **Are NVIDIA device nodes present in the container?**
   ```bash
   docker run --rm --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=all \
     -e NVIDIA_DRIVER_CAPABILITIES=graphics,compute,utility \
     local-llm-runner-vulkan:latest ls /dev/nvidia*
   ```
   If empty: nvidia-container-runtime is not configured — check `/etc/docker/daemon.json`.

2. **Is the EGL ICD file present in the image?**
   ```bash
   docker run --rm local-llm-runner-vulkan:latest \
     cat /usr/share/vulkan/icd.d/nvidia_egl_icd.json
   ```
   If missing: rebuild the image — `./runner/build.sh vulkan`.

3. **Test with explicit ICD and VK_LOADER_DEBUG:**
   ```bash
   docker run --rm --runtime=nvidia \
     -e NVIDIA_VISIBLE_DEVICES=all \
     -e NVIDIA_DRIVER_CAPABILITIES=graphics,compute,utility \
     -e VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_egl_icd.json \
     -e VK_LOADER_DEBUG=error \
     local-llm-runner-vulkan:latest llama-server --list-devices 2>&1
   ```
   - `Failed loading library`: EGL ICD not found → image out of date
   - `Could not get vkCreateInstance via vk_icdGetInstanceProcAddr`: wrong ICD (GLX)
   - Device appears: wiring is correct

### AMD ROCm: "No GPU found"

1. Check `/dev/kfd` exists and render group matches:
   ```bash
   ls -l /dev/kfd      # expect crw-rw---- render
   id                  # expect render in groups
   ```

2. Check `rocminfo` enumerates GPUs as agents (not just CPU):
   ```bash
   rocminfo | grep -E 'Agent|Marketing'
   ```

3. Check render group GID matches what's in `.env`:
   ```bash
   stat -c '%g' /dev/kfd     # GID number
   grep RENDER_GROUP .env    # should match
   ```

### CUDA: container exits with driver version error

The CUDA runtime version in the container must be ≤ host driver capability.
```
CUDA error: no kernel image is available for execution on the device
```
or driver version mismatch errors mean the `nvidia/cuda:X.Y.Z` base is too new
for the installed host driver. Lower the CUDA version in `runner/cuda/Dockerfile`.

### Mixed Vulkan: P40 (or NVIDIA GPU) not visible

If `--list-devices` inside the container shows only AMD cards:

1. **Check the NVIDIA graphics libs are bind-mounted:**
   ```bash
   docker inspect <container_name> | python3 -c 'import json,sys; d=json.load(sys.stdin)[0]; [print(b) for b in d["HostConfig"]["Binds"] if "nvidia" in b]'
   ```
   If only the models bind is shown (no nvidia libs), the mgmt container can't see
   `/host/nvidia-libs`. Check `docker-compose.yml` has the mount and restart mgmt:
   ```bash
   docker compose up -d local-llm-mgmt
   ```

2. **Check `libEGL_nvidia.so.0` can initialize:**
   ```bash
   docker exec <container_name> sh -c \
     'VK_LOADER_DEBUG=error VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_egl_icd.json \
      /usr/local/bin/llama-server --list-devices 2>&1'
   ```
   - `Could not get vkCreateInstance via vk_icdGetInstanceProcAddr`: the support libs
     are still missing. Check the bind mounts above.
   - `Found no drivers`: the EGL ICD file is missing — rebuild the Vulkan image.
   - Device appears: ICD works; the issue is elsewhere.

3. **Check `/dev/nvidia-modeset` is in the container:**
   ```bash
   docker exec <container_name> ls /dev/nvidia-modeset
   ```
   If missing, the cluster JSON has `"backend": "mixed_vulkan"` but the running
   container predates the code change. Stop and restart the runner.

### GPU not visible to GPU inventory (cluster setup fails)

The management container runs `rocminfo`, `nvidia-smi`, and `vulkaninfo` on startup.
If a GPU shows in `lspci` but not in cluster creation:

- AMD missing: Is `rocminfo` installed on the host? The management container
  bind-mounts the host's `/dev/kfd` and `/dev/dri` but runs its own `rocminfo`.
  Check: `docker exec local-llm-mgmt rocminfo`

- NVIDIA missing: `nvidia-smi` must be accessible inside the management container.
  The management container does not use the NVIDIA runtime — it probes via
  `nvidia-smi` which must be installed on the host and available on PATH,
  or via sysfs fallback.

- Vulkan missing: `vulkaninfo` must work inside the management container.
  For AMD Vulkan: the management container needs `/dev/kfd` and `/dev/dri`.
  For NVIDIA Vulkan: vulkaninfo is not used (NVIDIA Vulkan detection is
  based on `nvidia-smi` vendor detection + cluster backend being `vulkan`).

### "render" group GID mismatch

If AMD containers fail with permission errors on `/dev/kfd`:
```bash
# On host:
stat -c '%g' /dev/kfd          # get actual GID
# In .env:
RENDER_GROUP=<actual GID>
# Restart:
docker compose up -d
```

---

## Quick reference: what each image needs injected at runtime

| Image | Backend | Access method | Required host setup |
|-------|---------|-------------|---------------------|
| `local-llm-runner-rocm` | `rocm` | `/dev/kfd` + `/dev/dri` bind, render GID | AMDGPU kernel module, ROCm userspace |
| `local-llm-runner-cuda` | `cuda` | `nvidia` Docker runtime, `DeviceRequests` | NVIDIA kernel module, nvidia-container-toolkit |
| `local-llm-runner-vulkan` | `vulkan` (AMD) | `/dev/kfd` + `/dev/dri` bind, render GID | AMDGPU kernel module |
| `local-llm-runner-vulkan` | `vulkan` (NVIDIA) | `nvidia` Docker runtime with `graphics` capability, `VK_ICD_FILENAMES` | NVIDIA kernel module, nvidia-container-toolkit |
| `local-llm-runner-vulkan` | `mixed_vulkan` | Both AMD bind-mount and `nvidia` Docker runtime; NVIDIA graphics libs bind-mounted from host; `/dev/nvidia-modeset` | AMDGPU kernel module, NVIDIA kernel module, nvidia-container-toolkit; `/usr/lib/x86_64-linux-gnu:/host/nvidia-libs:ro` in mgmt container |
