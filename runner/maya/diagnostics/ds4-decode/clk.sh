#!/bin/bash
# sample busy%, current sclk and mclk per card every 0.25 s for $1 seconds
end=$((SECONDS + $1))
while [ $SECONDS -lt $end ]; do
  line="$(date +%s.%N | cut -c1-14)"
  for c in 0 1 2 3; do
    d=/sys/class/drm/card$c/device
    line="$line c$c $(cat $d/gpu_busy_percent) $(grep "\*" $d/pp_dpm_sclk | awk "{print \$2}") $(grep "\*" $d/pp_dpm_mclk | awk "{print \$2}")"
  done
  echo "$line"
  sleep 0.25
done
