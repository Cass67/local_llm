# Web-accessible coding agents: pi (TUI, via ttyd) and opencode (native web UI).
FROM node:22-slim

# Defaults are the reproducible pin for `docker compose build`; the Status tab's
# "Update coding agents" passes the current npm releases as build args instead.
# renovate: datasource=npm depName=@earendil-works/pi-coding-agent
ARG PI_VERSION=0.84.1
# renovate: datasource=npm depName=opencode-ai
ARG OPENCODE_VERSION=1.18.16
# OpenCode 2 beta, installed alongside v1 as the `opencode2` binary. Pinned to an
# exact prerelease rather than the @next tag: the beta moves daily and its config,
# server and plugin APIs are all still declared unstable upstream. No renovate
# comment -- the `latest` dist-tag does not track this line.
ARG OPENCODE2_VERSION=0.0.0-next-17428

ARG TTYD_VERSION=1.7.7

RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates ripgrep tini curl tmux \
    && rm -rf /var/lib/apt/lists/*

# ttyd is not packaged in Debian bookworm; use the upstream static binary.
RUN curl -fsSL -o /usr/local/bin/ttyd \
      "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.x86_64" \
    && chmod +x /usr/local/bin/ttyd \
    && ttyd --version

RUN npm install -g \
      "@earendil-works/pi-coding-agent@${PI_VERSION}" \
      "opencode-ai@${OPENCODE_VERSION}" \
      "@opencode-ai/cli@${OPENCODE2_VERSION}" \
    && npm cache clean --force

# Runs as the host user (see docker-compose `user:`) so files created in the
# mounted repos are not root-owned. HOME is fixed and world-writable so any uid
# can create the dirs the agents expect (~/.cache etc) alongside the bind mounts.
ENV HOME=/home/agent
# Pre-create the XDG tree: Docker would otherwise create these mount parents as
# root:755, and a non-root uid could not then mkdir ~/.local/state.
RUN mkdir -p /home/agent/.local/share /home/agent/.local/state \
             /home/agent/.config /home/agent/.cache \
    && chmod -R 0777 /home/agent

# Scrollback: the agents run inside tmux, which repaints the pane in place, so
# the browser terminal's own scrollback stays empty and the wheel does nothing.
# `mouse on` hands the wheel to tmux (copy-mode for pi, which paints on the main
# screen; passed through to any TUI that requests mouse tracking). Shift+drag
# still gives a native browser selection.
#
# Copy-mode then swallows every unbound key, which made the agents look frozen:
# pi sets neither mouse_any_flag nor alternate_on, so one stray wheel notch puts
# its pane in copy-mode, and with mode-keys=emacs a typed "/model" is silently
# discarded -- the screen has jumped into scrollback and nothing reaches pi.
# (opencode grabs the mouse, so it never enters copy-mode and only ever scrolls
# its own viewport.) So bind every printable key to cancel copy-mode and deliver
# itself: scroll to read history, start typing, and you are back with the
# keystroke intact. `q` is left as a pure cancel so it does not type a stray q;
# arrows, PageUp and the C-r/C-s search bindings are untouched.
RUN { printf '%s\n' \
        'set -g mouse on' \
        'set -g history-limit 50000'; \
      awk 'BEGIN{ \
        sq=sprintf("%c",39); dq=sprintf("%c",34); \
        for (i=32; i<127; i++) { \
          if (i==113) continue; \
          c=sprintf("%c",i); \
          q=(i==39)?dq:sq; \
          printf "bind -T copy-mode %s%s%s send -X cancel \\; send-keys -l %s%s%s\n", q,c,q,q,c,q; \
        } }'; \
    } > /home/agent/.tmux.conf \
    && chmod 0644 /home/agent/.tmux.conf

# ttyd serves one self-contained index.html with the xterm.js bundle inlined, and
# `-I` is the only hook for changing it. Pull ttyd's own page from a throwaway
# instance and splice in the touch/IME fixes, so nothing here is a fork of the
# upstream client -- a ttyd bump picks up its new page automatically.
COPY ttyd-touch.html /opt/ttyd/touch.html
RUN set -eu; \
    ttyd -p 7681 -i lo /bin/true & pid=$!; \
    for _ in 1 2 3 4 5 6 7 8 9 10; do \
      curl -fsS -o /tmp/ttyd-index.html http://127.0.0.1:7681/ && break; \
      sleep 0.5; \
    done; \
    kill "$pid"; \
    node -e 'const fs=require("fs"), \
      page=fs.readFileSync("/tmp/ttyd-index.html","utf8"), \
      patch=fs.readFileSync("/opt/ttyd/touch.html","utf8"); \
      if (!page.includes("</body>")) throw new Error("ttyd index.html has no </body>"); \
      fs.writeFileSync("/opt/ttyd/index.html", page.replace("</body>", patch + "</body>"));'

WORKDIR /work
ENTRYPOINT ["/usr/bin/tini", "--"]
