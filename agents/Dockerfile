# Web-accessible coding agents: pi (TUI, via ttyd) and opencode (native web UI).
FROM node:22-slim

ARG PI_VERSION=0.84.1
ARG OPENCODE_VERSION=1.18.16

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
RUN printf '%s\n' \
      'set -g mouse on' \
      'set -g history-limit 50000' \
      > /home/agent/.tmux.conf \
    && chmod 0644 /home/agent/.tmux.conf

WORKDIR /work
ENTRYPOINT ["/usr/bin/tini", "--"]
