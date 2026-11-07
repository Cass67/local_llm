# 7.4-rc1 test boot

Tested on ubt26 on 2026-11-06, including the user-authorized physical reboot.

## Current state

- Running kernel: `7.4.0-070400rc1-generic`, with `panic=30`.
- Saved GRUB default remains `7.2.13-ubt26`; the one-time entry was consumed.
- Temporary GRUB drop-in removed and configuration regenerated and checked.
- Old kernel and initramfs hashes unchanged from before installation.
- Secure Boot disabled. SSH, Docker and containerd active after boot; all four
  RX 7900 XT cards and `/dev/kfd` present.

SSH returned approximately 242 seconds after reboot. The existing GPU power-cap
service failed during startup with EBUSY; restarting that service succeeded and
restored the configured caps. NUT and OpenIPMI failures also occurred on the
previous boot and were not changed.

The user authorized GRUB tools to access `/boot/grub/grubenv` for this setup.
Boot-state and before/after metadata remain on the host under
`/mnt/scratch/maya-841/kernel-test`.

## QEMU result

QEMU/KVM booted the installed image with its generated initramfs and a
disposable 128 MiB ext4 root: correct kernel, read/write root, successful file
write/read, clean poweroff. Exit code 0, elapsed 5.8 seconds. Two virtual CPUs,
2 GiB RAM, no network, host disks, or GPU passthrough.

See `qemu-result.json` and `qemu-test.py`. This tests the virtual boot path;
physical GPUs, storage-controller, and networking initialization were subsequently
verified through the physical boot and workload tests.
`panic=30` reboots after a kernel panic. A hard hang still needs local recovery;
the available recovery is a keyboard and monitor.

## Packages and changes

All four official amd64 downloads passed SHA-256 checks against the amd64
manifest. Installed only the unsigned image and modules, version
`7.4.0-070400rc1.202611012313`; no upgrades or removals. Headers require
unavailable `libssl4` and were not installed. The host has no DKMS modules.
Public download hashes are in `kernel-packages.json`.

Remote changes: new kernel/module/initramfs files, regenerated grub.cfg,
consumed one-time boot state, and a regenerated grub.cfg. Temporary
`/etc/default/grub.d/99-maya-841-test.cfg` was removed after boot. Its historical
local source is `kernel-test-grub.cfg`. The running kernel retains `panic=30`;
future boots use the original command-line settings and saved old default.
Original grub.cfg and defaults were backed up with original permissions under
the root-only `/mnt/scratch/maya-841/kernel-test/backup` directory.

## Queue reproducer comparison

With unchanged TheRock HIP userspace and exclusive GPU access, both previously
failing controls completed successfully on the new kernel. The mixed-priority
repeat and eight-normal-stream control each retained nine compute queues but
settled at about 15 W and 16–17% activity on the target GPU. The old kernel
reported 100% and roughly 97 W. Thus the patch substantially improves power
consumption but leaves residual reported activity. The new amdgpu module contains
`amdgpu_mes_notify_unmap_queue` and `mes_notify_unmap_work_handler`.

Raw telemetry: `steps-clean-7.4.jsonl` and `steps-normal8-7.4.jsonl`.

## Full DS4 comparison

The unchanged v1.1.55 binary completed the automatic expert-share reload on
all four GPUs, reached ready, generated four tokens, and exited with code 0.
Default priorities were used, with `MAYA_DS4_TP_GGUF_UNEVEN=1`, auto shares,
vision and draft enabled, and the same 524288 context as the original test.

| Kernel/settings | Settled idle watts, cards 0 / 1 / 2 / 3 | Total | Activity |
| --- | --- | --- | --- |
| 7.2.13, default priorities | 88 / 104 / 84 / 104 | 380 W | 100% each |
| 7.4-rc1, default priorities | 14 / 15 / 14 / 16 | 59 W | 14–18% |
| 7.4-rc1, after generation | 14 / 15 / 16 / 16 | 61 W | 14–18% |
| 7.2.13, `DS4_STREAM_PRIO=0` | 11 / 5 / 10 / 18 | 44 W | 0% each |

Values are per-card medians; the first settling sample is excluded from the
new-kernel stages. There were 45 seconds of pre-request and 30 seconds of
post-request idle observation. This short functional check does not establish
throughput or long-context performance. Raw data and summary are in
`kernel74-auto-tp4.jsonl`, `kernel74-auto-tp4.out`, and `kernel74-results.json`.

The diagnostic container was stopped and the original GLM container restarted
with its original image and settings. No model profile or launcher was changed.
Final `/health` returned `status: ok`, model `maya-glm53-flash-q4xl-huihui`,
context 524288. Docker restart count was zero, all four cards were at 0% busy
with approximately 21.2 GB VRAM used each, and power was 7 / 10 / 8 / 12 W.
The power-cap service was active. See `kernel74-final-state.json`.

## Rollback

The next ordinary reboot selects the retained 7.2.13 kernel. No permanent
default change was made, and no further reboot is scheduled.
