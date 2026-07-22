#!/bin/sh
LOG=/tmp/p40-watch.log
START=$(date +%s)
find_fan() {
  for h in /sys/class/hwmon/hwmon*; do
    [ "$(cat "$h/name" 2>/dev/null)" = it8622 ] || continue
    v=$(cat "$h/fan4_input" 2>/dev/null || echo 0)
    [ "$v" -gt 1000 ] && {
      echo "$h"
      return
    }
  done
}
H=$(find_fan)
echo "=== start $(date -Is) kapton-gen3-zork fan_hwmon=$H ===" >>"$LOG"
while :; do
  TS=$(date -Is)
  FAN=$(cat "$H/fan4_input" 2>/dev/null || echo ERR)
  PWM=$(cat "$H/pwm4" 2>/dev/null || echo ERR)
  SMI=$(nvidia-smi --query-gpu=index,pci.bus_id,name,temperature.gpu,power.draw,power.limit,pstate,pcie.link.gen.current,pcie.link.width.current,utilization.gpu --format=csv,noheader,nounits 2>&1 | tr "\n" ";")
  XID=$(journalctl -k --since "@$START" --no-pager | grep -E "NVRM|Xid|fallen|AER|PCIe Bus Error" | tail -5 | tr "\n" "|")
  echo "$TS fan4=$FAN pwm4=$PWM smi=[$SMI] xid=[$XID]" >>"$LOG"
  case "$SMI" in *"Unknown Error"* | *"No devices were found"* | *"Unable to determine"*)
    echo "=== FAILURE $(date -Is) ===" >>"$LOG"
    journalctl -k --since "@$START" --no-pager | tail -160 >>"$LOG"
    exit 1
    ;;
  esac
  sleep 5
done
