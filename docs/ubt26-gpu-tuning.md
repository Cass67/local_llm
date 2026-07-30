# ubt26 GPU tuning

This records the non-default GPU tuning on `ubt26` and why it exists.

## Source of truth

Live script:

```text
/usr/local/sbin/ubt26-fan-tune
```

Repo copy:

```text
scripts/ubt26-fan-tune
```

Systemd unit:

```text
/etc/systemd/system/ubt26-fan-tune.service
```

The service is enabled and runs once at boot:

```bash
sudo systemctl restart ubt26-fan-tune.service
systemctl status ubt26-fan-tune.service --no-pager -l
```

## NVIDIA Tesla P40

Hardware path:

```text
P40 PCI device:        0000:07:00.0
P40 upstream port:     0000:00:1b.0
Connection:            M.2 -> OCuLink -> eGPU adapter -> Tesla P40
```

Current tuning:

```bash
# Enable persistence and cap P40 to its minimum supported power limit.
# ECC was disabled once with `sudo nvidia-smi -e 0` to expose full 24GB VRAM; it persists across reboots.
nvidia-smi -pm 1
nvidia-smi -i 0 -pl 125
```

Note: the earlier boot-time Gen2 `setpci` workaround was removed on 2026-07-21. The root port is no longer forced by `ubt26-fan-tune`.

Why:

- At Gen3 x4, the P40 repeatedly logged NVIDIA `Xid 79` / "GPU has fallen off the bus".
- This happened even near idle after swapping to a longer-cable M.2/OCuLink adapter.
- Earlier hardware had PCIe AER corrected errors; `pcie_aspm=off` helped those, but the new adapter produced hard off-bus failures.
- Gen2/Gen1 runtime tests helped diagnose signal-margin problems, but boot-time Gen2 forcing has been removed.
- ECC was disabled once to recover full 24GB VRAM for local inference; this is noted in the script, not rerun every boot.
- The P40 default power limit is 250 W, so the 125 W cap keeps transient load lower while testing.

Expected verification:

```bash
nvidia-smi --query-gpu=index,pci.bus_id,name,power.limit,power.draw,temperature.gpu,pcie.link.gen.current,pcie.link.width.current --format=csv,noheader,nounits
sudo lspci -vv -s 0000:00:1b.0 | grep -E 'LnkSta:|LnkCtl2:'
journalctl -k --since '10 minutes ago' --no-pager | grep -E 'NVRM|Xid|fallen|AER|PCIe Bus Error' || true
```

Good state looks like:

```text
Tesla P40 ECC:         disabled
Tesla P40 power.limit: 125 W
PCIe current link:    Gen3 x4 normally, or manually forced lower only for diagnostics
No fresh Xid/AER logs
```

## P40 fan header

The external P40 fan/blower tach is on the motherboard IT8622 controller:

```text
it8622-isa-0a40 fan4
/sys/devices/platform/it87.2624/hwmon/hwmon*/fan4_input
```

Do not run this header too low. `pwm4=55` produced about 1040 RPM and was followed by a P40 off-bus failure. Keep it around the existing automatic/manual range (`pwm4` around 70-80, roughly 1400-1650 RPM during the observed runs) unless retesting carefully.

Quick read:

```bash
for h in /sys/class/hwmon/hwmon*; do
  [ "$(cat "$h/name" 2>/dev/null)" = it8622 ] || continue
  v=$(cat "$h/fan4_input" 2>/dev/null || echo 0)
  [ "$v" -gt 1000 ] && printf '%s fan4=%s pwm4=%s enable=%s\n' "$h" "$v" "$(cat "$h/pwm4")" "$(cat "$h/pwm4_enable")"
done
```

## AMD 7900 XT cards

`ubt26-fan-tune` also applies AMD tuning for `card0` and `card1`:

- custom fan curves via `/sys/class/drm/card*/device/gpu_od/fan_ctrl`
- manual DPM mode
- power profile mode `4`
- selected SCLK/MCLK DPM states
- core clock target `s 1 1900`
- voltage offset `vo -75`
- power caps:
  - `card0`: `238000000` microwatts = 238 W
  - `card1`: `253000000` microwatts = 253 W

These were pre-existing in the live tune script before the P40 Gen2 change.

### RCCL load and clock finding

The first uncapped two-card ROCm/RCCL tensor request hard-reset the host at roughly
488 W combined GPU socket power and ~2.9 GHz. With the persisted 1900 MHz ceiling
restored, the repeated workload was stable, peaked near 306 W combined, and
observed about 1.995 GHz. No higher clock is needed for the accepted performance:
forcing hipBLAS, not clocking, reduced the full 92k request from 35.10 s to
18.03–18.64 s.

Keep telemetry running for new tensor shapes and stop tests that exceed the proven
power envelope. The 230 W cap attempted during diagnosis is unsupported; firmware
minimums are 238 W and 253 W. Full performance and VRAM results:
[ROCm/RCCL tensor + hipBLAS](multi-gpu-parallelism-findings-2026-07-30.md#local-rccl-result).

## Rollback

Backups currently known on `ubt26`:

```text
/usr/local/sbin/ubt26-fan-tune.bak.20260719-000130  # before P40 125 W default
/usr/local/sbin/ubt26-fan-tune.bak.20260719-003543  # before adding P40 Gen2 retrain
/usr/local/sbin/ubt26-fan-tune.bak.20260722-171027-p40-ecc-off  # before adding the ECC note
/usr/local/sbin/ubt26-fan-tune.bak.20260730-143651-pre-1900-restore  # before restoring 1900 MHz
```

Re-apply the old Gen2 workaround if needed:

```bash
sudo cp -a /usr/local/sbin/ubt26-fan-tune.bak.20260721-133943-remove-p40-gen2 /usr/local/sbin/ubt26-fan-tune
sudo systemctl restart ubt26-fan-tune.service
```

Rollback both Gen2 and P40 power-cap default change:

```bash
sudo cp -a /usr/local/sbin/ubt26-fan-tune.bak.20260719-000130 /usr/local/sbin/ubt26-fan-tune
sudo systemctl restart ubt26-fan-tune.service
```

Runtime-only Gen3 restore without editing the script:

```bash
sudo setpci -s 0000:00:1b.0 CAP_EXP+30.w=0003:000f
sudo setpci -s 0000:00:1b.0 CAP_EXP+10.w=0020:0020
```

That will be overwritten by `ubt26-fan-tune.service` on next restart/boot unless the script is changed.

## Watcher used during debugging

A temporary watcher was run from:

```text
/tmp/p40-watch.sh
/tmp/p40-watch.log
```

It logs P40 temp, power, cap, PCIe gen/width, utilization, fan RPM/PWM, and fresh kernel Xid/AER lines. It is diagnostic only, not the source of truth.
