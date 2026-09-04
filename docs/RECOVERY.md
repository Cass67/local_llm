# Recovery

Rebuilding the stack on a bare host. Written against ubt26 (Ubuntu 26.04 LTS,
kernel 6.19, 3x RX 7900 XT), but nothing here is host-specific except the disk
layout in step 2.

Order matters: step 0 is the part git cannot give you, and it is the part that
will block you at the end if you skip it.

## 0. Things that are NOT in git

Collect these before starting. Everything else is reproducible from a clone.

| Item | Where it lives | Notes |
|---|---|---|
| `.env` values | password manager | 6 keys, see below |
| `opencode` / `opencode2` credentials | `~/.config/local_llm/agents/*/auth.json` | re-obtainable: `opencode auth login`, `opencode2 auth login` |
| Cloudflare tunnel ingress | Zero Trust dashboard → Tunnels → Public Hostnames | **dashboard-only, no CLI, no file**; cloudflared pulls config remotely and ignores `~/.cloudflared/config.json` |
| Model cache | `/mnt/hfcache` | large; re-downloadable from HF, slow |
| Profile history | `/state/profile-snapshots`, `/state/*.bak` | only the current `profiles.json` is in git |

`.env` keys (values redacted — this file is gitignored by `*env*`):

```
HF_TOKEN=              # HF downloads, gated repos
GITHUB_TOKEN=          # update checks; unauthenticated is 60 req/h and runs out mid-check
LANGFUSE_SECRET_KEY=   # tracing
LANGFUSE_PUBLIC_KEY=
LANGFUSE_PUBLIC_URL=
AGENTS_REPO_DIR=       # host dir mounted into the agent containers
```

## 1. Host prerequisites

```bash
scripts/bootstrap-host.sh            # read-only audit, safe on a live box
scripts/bootstrap-host.sh --install  # install what is missing
```

It covers, and is the authoritative list:

- **apt**: `docker.io git curl jq rsync python3 nodejs npm lm-sensors ca-certificates rocminfo rocm-smi`
- **docker CLI plugins**: `compose` and `buildx` are hand-installed binaries in
  `~/.docker/cli-plugins/` — **apt does not provide them**, and `deploy.sh` fails
  without both
- **groups**: `docker`, `video`, `render` (the last two for `/dev/kfd`, `/dev/dri`);
  log out and back in after
- **kernel modules**: `nct6775` (chassis fans) and `corsair_psu` (PSU telemetry),
  persisted to `/etc/modules-load.d/` — they load fine at runtime but are lost on
  reboot otherwise
- **case-fan daemon**: installs `ubt26-airflowd` to `/usr/local/sbin` and enables
  the unit. The BIOS fan curve is CPU-keyed, so without this the chassis fans do
  not respond to GPU junction temp.

Not automated: `cloudflared` needs Cloudflare's apt repo. The ROCm packages above
are diagnostics only — the runner images carry their own ROCm userspace.

## 2. Disks

`/state` is a bind mount at `~/.local/share/local_llm`, on the root filesystem —
it comes back with the OS. The model cache is separate and large:

```
/mnt/hfcache      ext4   500G nvme, HF model cache
/mnt/spare        ext4   scratch for large builds/downloads
```

`/tmp` is cleared on reboot — use `~/scratch` or `/mnt/spare` for big work.

## 3. Clone and seed

```bash
git clone <remote> ~/git/local_llm && cd ~/git/local_llm
cp /path/to/saved.env .env          # step 0
scripts/state-init.sh               # seeds /state/profiles.json (74 families)
scripts/agents-init.sh              # seeds pi + opencode config
```

Both seeders only write when the destination is absent, so they are safe to
re-run and will never clobber live state. `state-init.sh --export` refreshes the
committed `configs/profiles.json` from the live one — do that after tuning, or
the export goes stale.

## 4. Deploy

```bash
./deploy.sh
```

Pushes local commits, pulls on the host, rebuilds `ui-dist`, then
`docker compose build && up -d`. It refuses to run while a job is in flight
(build, sweep, benchmark, bakeoff, speed-bench); `FORCE_DEPLOY=1` overrides.

Ports — Caddy on **:3001** is the whole site; everything else is an upstream
bound to loopback:

| Port | Service | Path via :3001 |
|---|---|---|
| 3001 | Caddy | — |
| 3100 | mgmt API + UI | `/ui/`, `/api/local-llm/*` |
| 3200 | model router | `/v1/*` |
| 3101 | Open WebUI | `/` |
| 3006 | pi | `/pi/` |
| 3002 | OpenCode v1 | `/opencode/` |
| 3009 | OpenCode 2 beta | `/opencode2/` |
| 3004 | Langfuse | `/traces` |
| 3007 | Grafana | `/metrics/` |
| 3008 | Prometheus | — |
| 3005 | SearxNG | — |
| 5433 | Postgres (Langfuse) | — |

The agent terminals bind `127.0.0.1` deliberately; reach them through :3001, not
`host:3006`. Cloudflare proxies only a fixed port list, so any `host:<port>` link
hangs over the tunnel rather than failing fast.

## 5. Manual steps after deploy

1. **Tunnel hostnames** — Zero Trust → Tunnels → Public Hostnames. Do *not* run
   `cloudflared tunnel route dns` first: it creates the CNAME and the dashboard
   form then refuses with "already exists".
2. **OpenCode 2 login** — `opencode2 auth login` inside the container; v2 does not
   read v1's `auth.json`.
3. **Langfuse** — register at the UI, create a project, put the keys in `.env`.
4. **Restore extras** — `scripts/backup.sh restore <path>` for snapshot history;
   `agents/pi-extensions/llama-cpp.ts` → `~/.pi/agent/extensions/` for the Mac pi.

## 6. Backups

A daily timer (`local-llm-backup.timer`, 03:30 + up to 15m jitter, `Persistent=true`)
runs `scripts/backup-full.sh` as root and writes to `/mnt/spare/local_llm-backups`,
keeping 14 archives. ~1 GB each, ~30s to make.

The destination must not be the root disk — `/state`, the docker volumes, `.env`
and the agent config all live on `nvme0n1`. `/mnt/spare` is `nvme1n1` and
`sda` is being converted into the new root disk (docs/plans/boot-disk-swap-uefi.md),
so `/mnt/spare` is the only valid destination.

Contents, and why each is there:

| Component | Note |
|---|---|
| `env` | the 6 secrets; **this is why the archive is 0600 and must not be synced casually** |
| `cloudflared/` | tunnel credentials — lose them and the tunnel must be recreated |
| `agents.tar` | opencode/opencode2 `auth.json` plus pi + opencode session history |
| `state.tar` | `profiles.json`, profile snapshots, speed-bench (`runs/` excluded) |
| `langfuse.sql` | `pg_dump`, **not** a file copy — a live data dir copies torn |
| `open-webui.tar` | container is paused for the copy; the image has no `sqlite3`, so there is no online `.backup` |

Excluded on purpose: `/mnt/hfcache` (244 GB, re-downloadable) and `/state/runs`
(benchmark history, not function).

```bash
sudo scripts/backup-full.sh                       # manual run
systemctl list-timers local-llm-backup            # when it next fires
journalctl -u local-llm-backup -n 20              # what it did
```

Restoring — nothing is written without `--yes`, and existing targets are moved to
`<path>.pre-restore-<ts>` rather than overwritten:

```bash
scripts/restore-full.sh <archive>                          # list, change nothing
sudo scripts/restore-full.sh <archive> --yes --into /tmp/p # stage to scratch first
sudo scripts/restore-full.sh <archive> --yes               # restore in place
sudo scripts/restore-full.sh <archive> --yes --only state,env
```

Verified end to end: an archive restores to 74 profile families, and
`langfuse.sql` reloads into a scratch database with matching table and row counts.
Restoring `langfuse` drops and recreates the database, because `pg_dump` output is
not idempotent against a populated one.

**Off-host copy is still TODO.** Everything above is one machine; a second copy
pulled to another box is what actually protects against losing ubt26.

## 7. Verify

```bash
scripts/bootstrap-host.sh                          # all green
curl -s localhost:3100/v1/models | jq '.data[].id' # models advertised
curl -so /dev/null -w '%{http_code}\n' localhost:3001/ui/
for p in pi opencode opencode2; do
  curl -so /dev/null -w "$p %{http_code}\n" "localhost:3001/$p/"
done
systemctl is-enabled ubt26-airflowd
sensors | grep -i fan | head
```
