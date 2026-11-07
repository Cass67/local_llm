# T7910 PCIe peer-access investigation

Work in progress, 2026-11-07. User authorized kernel/host tests after the initial read-only diagnosis.

Source of truth: scripts in this directory; upstream Linux v7.4-rc1 plus the generated Dell-scoped patch. Remote experiment lives at `/mnt/scratch/t7910-p2p`. Model profiles and runner images are unchanged. Kernel/boot changes are diagnostic only.

## Established before the experiment

- BIOS A34, two Xeon E5-2699C v4 processors, two NUMA nodes.
- Read-only Dell SMBIOS queries report Home Snoop active, Cluster-on-Die off, Isochronous mode off. Node Interleave tokens 01c4/01c5 cannot be read; the OS exposes NUMA.
- GPUs 05:00.0 and 08:00.0 are on root pci0000:00 / NUMA 0. GPUs a3:00.0 and a6:00.0 are on root pci0000:a0 / NUMA 1.
- All GPU links are PCIe 3 x16, BARs 32 GiB, amdgpu.pcie_p2p enabled, IOMMU domains identity.
- HIP allows only 0 <-> 1. Direct 64 MiB kernel reads and writes for that pair pass changing-pattern integrity checks in both directions.
- Linux identifies CPU0 root by 8086:6f00 (allowed only within one host bridge), CPU1 by its first root-port device 8086:6f04 (not allowed). Cross-root pairs are separately excluded by REQ_SAME_HOST_BRIDGE.
- Maya v1.1.56 also disables its DS4_AR_P2P hub buffers on HIP because of issue #809. Hardware transfers passing would not validate that allreduce path.

## Experiment

`prepare-kernel.py` makes a reduced host-module config from the existing 7.4-rc1 config. It patches only this Dell model: permit 6f00/6f04 roots within one host bridge; allow cross-root experiments only with `t7910_p2p_cross=1`. Default is local-only.

`peer-check.cpp` tests direct GPU kernel reads and writes rather than a HIP copy that could stage through RAM. Each direction tests three changing 64 MiB patterns. `run-checks.py` bounds each process and stops at the first failure.

The new kernel passed an isolated QEMU boot with writable ext4 root. `install-kernel.py` installs beside the originals and verifies the original 7.4 kernel/initramfs hashes. `arm-boot.py` creates local/cross diagnostic entries and arms only the next boot. The existing saved default remains 7.2.13-ubt26.

## Local-only physical boot result

`7.4.0-rc1-t7910-p2p` with `t7910_p2p_cross=0` booted successfully. HIP now permits both same-socket pairs (0/1 and 2/3), and still excludes cross-socket pairs. All four directed local-pair checks passed three 64 MiB read/write patterns. This confirms that CPU1’s missing allowlist entry blocked a functional local path. See `checks-local.json`. BIOS settings were unchanged.

## Current user direction

The user explicitly requested keeping the patched kernel active and testing Claude’s existing four-card path. A restore reboot was already sent when that steering arrived; after it completed the host was booted back into the patched cross-enabled kernel. Do not automatically restore the old kernel. Production profiles/images remain unchanged.

## Rollback

Boot the retained `7.4.0-070400rc1-generic` image to restore the kernel that was running before this experiment. The saved normal default is still 7.2.13-ubt26. Remove `/etc/grub.d/42_t7910_p2p` and regenerate grub.cfg when finished. Original generated grub.cfg is in the root-only `boot-backup` directory. Restore cluster 0663b08f with family maya-dsv41-q4xl-huihui / profile default and restart local-llm-router after diagnostics.

A kernel panic is configured to reboot after 30 seconds. A hard hardware hang may require the local keyboard/monitor; QEMU does not validate physical PCIe routing.

The scripts that built and installed the test kernels, edited the boot config and drove QEMU are not kept in the repo:
archive `ubt26:/mnt/scratch/t7910-p2p/dropped-scripts-20261107.tgz`.
