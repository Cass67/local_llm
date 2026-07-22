#!/bin/sh
ssh ubt26 'printf "== nvidia-smi PCIe ==\n"; nvidia-smi --query-gpu=index,pci.bus_id,name,pcie.link.gen.current,pcie.link.width.current,pcie.link.gen.max,pcie.link.width.max,power.draw,temperature.gpu --format=csv,noheader,nounits 2>&1 || true
 GPU=$(nvidia-smi --query-gpu=pci.bus_id --format=csv,noheader,nounits 2>/dev/null | head -1 | sed "s/00000000:/0000:/" ||
 true)
 printf "== GPU addr ==\n%s\n" "${GPU:-none}"
 if [ -n "${GPU:-}" ] && [ -e "/sys/bus/pci/devices/$GPU" ]; then
   PORT=$(basename "$(dirname "$(readlink -f "/sys/bus/pci/devices/$GPU")")")
   printf "== upstream port ==\n%s\n" "$PORT"
   printf "== port link ==\n"; sudo -n lspci -vv -s "$PORT" | grep -E "LnkCap:|LnkSta:|LnkCtl2:" || true
   printf "== gpu link ==\n"; sudo -n lspci -vv -s "$GPU" | grep -E "LnkCap:|LnkSta:|LnkCtl2:" || true
 fi
 printf "== recent errors ==\n"; journalctl -k --since "10 minutes ago" --no-pager | grep -E "NVRM|Xid|fallen|AER|PCIe Bus
 Error" | tail -30 || true'
