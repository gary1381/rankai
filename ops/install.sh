#!/usr/bin/env bash
# Install the rankai systemd user units with this checkout and a Python interpreter filled in.
# Usage: ops/install.sh [/path/to/python3]     (default: the python3 on PATH)
# Then:  systemctl --user daemon-reload && systemctl --user enable --now rankai-ingest.timer [rankai-web.service]
set -euo pipefail
home=$(cd "$(dirname "$0")/.." && pwd)
py=${1:-$(command -v python3)}
dest=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
mkdir -p "$dest"
for u in rankai-ingest.service rankai-ingest.timer rankai-web.service; do
  sed -e "s|RANKAI_HOME|$home|g" -e "s|RANKAI_PYTHON|$py|g" "$home/ops/$u" > "$dest/$u"
  echo "wrote $dest/$u"
done
