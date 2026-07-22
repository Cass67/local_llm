# P40 eGPU debug log — 2026-07-19

Short version: the P40 eGPU path is electrically marginal. Gen3 falls over fast, Gen2 lasts longer but still falls, Gen1 survives much longer. Temps are fine and PCIe bandwidth is not maxed. The bad part is almost certainly the long/exposed M.2→OCuLink adapter/cable path.

## Hardware involved

- Host: `ubt26`
- GPU: NVIDIA Tesla P40 at `0000:07:00.0`
- Upstream PCIe root port: `0000:00:1b.0`
- Path: `M.2 slot -> M.2/OCuLink adapter/cable -> AOOSTAR EG02/eGPU -> Tesla P40`
- eGPU PSU: 250 W
- P40 default power limit: 250 W

## Symptoms

Kernel failure:

```text
NVRM: Xid (PCI:0000:07:00): 79, GPU has fallen off the bus.
NVRM: Xid (PCI:0000:07:00): 154, GPU recovery action changed ... GPU Reset Required
```

After that:

```text
nvidia-smi: Unable to determine the device handle for GPU0: 0000:07:00.0: Unknown Error
```

`llama-server` then segfaults or logs CUDA unknown errors because its GPU disappeared.

## What was tested

### Fan change

P40 external fan tach/header mapping found:

```text
it8622-isa-0a40 fan4
/sys/devices/platform/it87.2624/hwmon/hwmon*/fan4_input
```

Lowering to `pwm4=55` dropped fan to about 1040 RPM and was followed by a P40 off-bus event. Do not use that as a normal setting.

Observed safer range:

```text
pwm4 around 70-80
fan4 around 1400-1650 RPM under normal bench load
```

### P40 power cap

P40 minimum supported cap is 125 W. `120W` is invalid.

Applied live and in boot tune script:

```bash
nvidia-smi -pm 1
nvidia-smi -i 0 -pl 125
```

Result: power cap alone did **not** fix off-bus failures.

### PCIe Gen3

Default/current hardware capability:

```text
Gen3 x4 / 8GT/s x4
```

Failure: fast/repeated Xid 79, sometimes within ~3 minutes, and once even near idle.

### PCIe Gen2

Runtime command:

```bash
sudo setpci -s 0000:00:1b.0 CAP_EXP+30.w=0002:000f
sudo setpci -s 0000:00:1b.0 CAP_EXP+10.w=0020:0020
```

Expected:

```text
LnkSta: Speed 5GT/s, Width x4
nvidia-smi pcie.link.gen.current = 2
```

Result: much better, but still eventually failed around 20+ minutes under real P40/Zork bench load.

### PCIe Gen1

Runtime command:

```bash
sudo setpci -s 0000:00:1b.0 CAP_EXP+30.w=0001:000f
sudo setpci -s 0000:00:1b.0 CAP_EXP+10.w=0020:0020
```

Expected:

```text
LnkSta: Speed 2.5GT/s, Width x4
nvidia-smi pcie.link.gen.current = 1
```

Result: survived much longer. Around 25+ minutes observed, with no Xid/AER. Token rate dropped from roughly low/mid 40s to about 38 tok/s on later run.

## Important observations

### Not core thermal

P40 core temp stayed around 56-59°C under load. No thermal spike before failures.

### Not PCIe bandwidth saturation

At Gen1 x4, `nvidia-smi dmon` showed roughly:

```text
rxpci: ~73-86 MB/s
txpci: ~67-68 MB/s
```

Gen1 x4 has roughly ~1 GB/s usable per direction, so the link was nowhere near saturated.

Token loss from Gen1 is likely latency/sync overhead and 125 W cap, not bandwidth saturation.

### Likely root cause

Signal integrity / mechanical/electrical quality of the adapter/cable path.

Evidence:

- Old adapter had AER corrected errors but not frequent hard off-bus.
- New adapter with longer/exposed cable causes repeated hard Xid 79.
- Lower PCIe generation improves stability.
- Temps and bandwidth do not explain the failures.
- Amazon review for the bad-style product mentioned needing insulating tape around exposed single cables to avoid signal loss when touching case metal. That is a red flag.

## Current live state at time of this note

Runtime state:

```text
P40 currently forced to Gen1 x4
P40 power cap: 125 W
```

Boot script state as of 2026-07-21:

```text
/usr/local/sbin/ubt26-fan-tune no longer forces Gen2/Gen1.
The root port target was restored to Gen3 runtime, but current bad adapters still show x0/no GPU when they fail to power/link.
```

## Persistent script and service

Live tune script:

```text
/usr/local/sbin/ubt26-fan-tune
```

Systemd unit:

```text
/etc/systemd/system/ubt26-fan-tune.service
```

Restart/apply:

```bash
sudo systemctl restart ubt26-fan-tune.service
systemctl status ubt26-fan-tune.service --no-pager -l
```

Current script P40 section uses only the 125 W cap; no `setpci` forcing:

```bash
nvidia-smi -i 0 -pl "${P40_POWER_LIMIT_W:-125}"
```

## Rollback / restore commands

### Runtime only: restore Gen3

```bash
sudo setpci -s 0000:00:1b.0 CAP_EXP+30.w=0003:000f
sudo setpci -s 0000:00:1b.0 CAP_EXP+10.w=0020:0020
```

### Runtime only: set Gen2

```bash
sudo setpci -s 0000:00:1b.0 CAP_EXP+30.w=0002:000f
sudo setpci -s 0000:00:1b.0 CAP_EXP+10.w=0020:0020
```

### Runtime only: set Gen1

```bash
sudo setpci -s 0000:00:1b.0 CAP_EXP+30.w=0001:000f
sudo setpci -s 0000:00:1b.0 CAP_EXP+10.w=0020:0020
```

### Verify link/cap

```bash
nvidia-smi --query-gpu=index,pci.bus_id,name,power.limit,power.draw,temperature.gpu,pcie.link.gen.current,pcie.link.width.current --format=csv,noheader,nounits
sudo lspci -vv -s 0000:00:1b.0 | grep -E 'LnkSta:|LnkCtl2:'
journalctl -k --since '10 minutes ago' --no-pager | grep -E 'NVRM|Xid|fallen|AER|PCIe Bus Error' || true
```

### Restore tune script from backups

Backups created:

```text
/usr/local/sbin/ubt26-fan-tune.bak.20260719-000130  # before P40 125 W default
/usr/local/sbin/ubt26-fan-tune.bak.20260719-003543  # before adding P40 Gen2 retrain
/usr/local/sbin/ubt26-fan-tune.bak.20260721-133943-remove-p40-gen2  # before removing Gen2 retrain
```

Rollback only Gen2 retrain, keep whatever was in that backup:

```bash
sudo cp -a /usr/local/sbin/ubt26-fan-tune.bak.20260719-003543 /usr/local/sbin/ubt26-fan-tune
sudo systemctl restart ubt26-fan-tune.service
```

Rollback to before P40 power-cap default change:

```bash
sudo cp -a /usr/local/sbin/ubt26-fan-tune.bak.20260719-000130 /usr/local/sbin/ubt26-fan-tune
sudo systemctl restart ubt26-fan-tune.service
```

## Replacement plan

Refund started for bad 40 cm JMT-style M.2→OCuLink exposed cable adapter.

Better physical path:

```text
M.2 slot -> tiny rigid M.2/OCuLink host adapter -> thick shielded AOOSTAR EG02 OCuLink cable -> EG02 -> P40
```

Candidate adapter style:

```text
NFHK 2280 PCI-E4.0 M.2 M-key to OCuLink SFF-8612/SFF-8611 Vertical Host Adapter
```

After replacement arrives:

1. Install rigid M.2 host adapter.
2. Use thick shielded EG02 OCuLink cable.
3. Boot and test Gen3 first.
4. Run P40 bench with watcher.
5. If Gen3 stable, remove/relax Gen2 script workaround and update docs.
6. If Gen3 fails but Gen2 stable, keep Gen2.
7. If Gen2 fails too, return replacement or retire P40/eGPU path.

## Temporary watcher

Watcher files used:

```text
/tmp/p40-watch.sh
/tmp/p40-watch.log
/tmp/p40-watch.pid
```

It logs:

- P40 temp/power/cap/util
- PCIe gen/width
- fan RPM/PWM
- fresh NVRM/Xid/AER kernel lines

Start a fresh watcher if needed rather than trusting old logs.
