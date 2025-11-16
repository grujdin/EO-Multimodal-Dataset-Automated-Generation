#!/usr/bin/env bash
# setup_orin.sh — Fresh JetPack → auto-mount SSD, Docker (nvidia runtime) on /ssd, current Ollama + Open WebUI,
# and idempotent swap on /ssd. Safe defaults: NO formatting unless --format-ssd is passed.

set -euo pipefail

# ---------- Tunables (override via env or flags) ----------
SSD_MP="${SSD_MP:-/ssd}"                # mountpoint
SSD_DEV="${SSD_DEV:-}"                  # if empty, auto-detect
FORMAT_SSD="${FORMAT_SSD:-false}"       # or pass --format-ssd to allow mkfs.ext4 (DANGEROUS: wipes disk)

DOCKER_DATA="${DOCKER_DATA:-$SSD_MP/docker}"
OLLAMA_MODELS_DIR="${OLLAMA_MODELS_DIR:-$SSD_MP/ollama}"
OPENWEBUI_DATA="${OPENWEBUI_DATA:-$SSD_MP/open-webui}"

# Swap
ENABLE_SWAP="${ENABLE_SWAP:-true}"
SWAP_SIZE_GB="${SWAP_SIZE_GB:-16}"
SWAP_FILE="${SWAP_FILE:-$SSD_MP/${SWAP_SIZE_GB}G.swap}"
SWAPPINESS="${SWAPPINESS:-10}"          # 10–20 is typical for LLMs on Jetson

# Flags: --format-ssd, --ssd-dev=/dev/nvme0n1p1, --ssd-mp=/ssd
for arg in "$@"; do
  case "$arg" in
    --format-ssd) FORMAT_SSD=true ;;
    --ssd-dev=*)  SSD_DEV="${arg#*=}" ;;
    --ssd-mp=*)   SSD_MP="${arg#*=}" ;;
    *) echo "Unknown arg: $arg"; exit 1 ;;
  esac
done

die(){ echo "ERROR: $*" >&2; exit 1; }
need(){ command -v "$1" >/dev/null 2>&1 || die "Missing: $1"; }

[ "$(id -u)" -eq 0 ] || die "Run with sudo"

echo "=== Jetson bootstrap ==="
echo "SSD mountpoint  : $SSD_MP"
echo "Requested SSD    : ${SSD_DEV:-<auto-detect>}"
echo "FORMAT_SSD       : $FORMAT_SSD (DANGEROUS if true)"
echo "Docker data-root : $DOCKER_DATA"
echo "Ollama models    : $OLLAMA_MODELS_DIR"
echo "Open WebUI data  : $OPENWEBUI_DATA"
echo "Swap             : ENABLE=$ENABLE_SWAP  SIZE=${SWAP_SIZE_GB}G  FILE=$SWAP_FILE  swappiness=$SWAPPINESS"
echo

need lsblk; need awk; need sed; need grep

# ---------- 0) Auto-detect NVMe device/partition & mount safely ----------
mkdir -p "$SSD_MP"

if mountpoint -q "$SSD_MP"; then
  echo "[ok] $SSD_MP already mounted"
else
  # If user specified a device, use it; otherwise try to find an ext* NVMe partition first, then a disk
  if [ -z "$SSD_DEV" ]; then
    # First ext* partition on NVMe (preferred)
    SSD_DEV="$(lsblk -nrpo NAME,TYPE,FSTYPE | awk '$1 ~ /nvme/ && $2=="part" && $3 ~ /^ext/ {print $1; exit}')"
    # If none, allow single-filesystem disk (ext*) like /dev/nvme0n1
    if [ -z "$SSD_DEV" ]; then
      SSD_DEV="$(lsblk -nrpo NAME,TYPE | awk '$1 ~ /nvme/ && $2=="disk" {print $1; exit}')"
    fi
    [ -n "$SSD_DEV" ] || die "No NVMe device found. Plug NVMe and rerun or pass --ssd-dev=/dev/...."
  fi

  # If device has no filesystem, format only if allowed
  if ! blkid "$SSD_DEV" >/dev/null 2>&1; then
    $FORMAT_SSD || die "$SSD_DEV has no filesystem. Re-run with --format-ssd to mkfs.ext4 (WIPES DISK)."
    echo "[!] Formatting $SSD_DEV as ext4 (you requested --format-ssd)"
    mkfs.ext4 -F -L NVME "$SSD_DEV"
  fi

  echo "[i] Mounting $SSD_DEV at $SSD_MP"
  mount "$SSD_DEV" "$SSD_MP"

  # Add /etc/fstab by UUID if missing
  UUID="$(blkid -o value -s UUID "$SSD_DEV")"
  if ! grep -q "$UUID" /etc/fstab; then
    echo "UUID=$UUID  $SSD_MP  ext4  defaults,noatime  0  2" >> /etc/fstab
    echo "[i] Added fstab entry for $SSD_MP"
  fi
fi

echo "[ok] SSD: $(df -h "$SSD_MP" | tail -1)"

# ---------- 1) Base packages ----------
apt-get update
apt-get install -y curl ca-certificates gnupg lsb-release git rsync jq

# ---------- 2) Docker (engine + nvidia default runtime, data-root on /ssd) ----------
if ! command -v docker >/dev/null 2>&1; then
  echo "[i] Installing Docker CE..."
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $UBUNTU_CODENAME stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

mkdir -p /etc/docker
STAMP=$(date +%Y%m%d-%H%M%S)
[ -f /etc/docker/daemon.json ] && cp -an /etc/docker/daemon.json "/etc/docker/daemon.json.bak.$STAMP"

cat >/etc/docker/daemon.json <<JSON
{
  "runtimes": { "nvidia": { "path": "nvidia-container-runtime", "runtimeArgs": [] } },
  "default-runtime": "nvidia",
  "data-root": "$DOCKER_DATA"
}
JSON

systemctl daemon-reload
systemctl restart docker
usermod -aG docker "${SUDO_USER:-$USER}" || true

# migrate old /var/lib/docker if present and not yet moved
if [ -d /var/lib/docker ] && [ ! -d "$DOCKER_DATA" ]; then
  echo "[i] Migrating /var/lib/docker => $DOCKER_DATA"
  mkdir -p "$DOCKER_DATA"
  rsync -aAXH --numeric-ids /var/lib/docker/ "$DOCKER_DATA"/
fi

echo "[ok] Docker Root Dir: $(docker info 2>/dev/null | awk -F': ' '/Root Dir/{print $2}')"
echo "[ok] Default Runtime: $(docker info 2>/dev/null | awk -F': ' '/Default Runtime/{print $2}')"

# ---------- 3) Swap on /ssd (idempotent, secure) ----------
if [ "$ENABLE_SWAP" = "true" ] && [ "$SWAP_SIZE_GB" -gt 0 ]; then
  echo "[i] Configuring swap: ${SWAP_SIZE_GB}G at $SWAP_FILE"
  # Jetson often enables zram swap by default:
  systemctl disable --now nvzramconfig 2>/dev/null || true
  systemctl disable --now zram-config 2>/dev/null || true

  if [ ! -f "$SWAP_FILE" ]; then
    fallocate -l "${SWAP_SIZE_GB}G" "$SWAP_FILE"
    chmod 600 "$SWAP_FILE"
    mkswap "$SWAP_FILE"
  else
    chmod 600 "$SWAP_FILE"
    file "$SWAP_FILE" | grep -q "swap file" || mkswap "$SWAP_FILE"
  fi

  swapon "$SWAP_FILE" 2>/dev/null || true

  # Persist in fstab once
  if ! grep -qF "$SWAP_FILE none swap sw 0 0" /etc/fstab; then
    echo "$SWAP_FILE none swap sw 0 0" >> /etc/fstab
  fi

  # Tune swappiness
  mkdir -p /etc/sysctl.d
  echo "vm.swappiness=$SWAPPINESS" > /etc/sysctl.d/99-swap.conf
  sysctl -p /etc/sysctl.d/99-swap.conf || true
else
  echo "[i] Swap creation skipped (ENABLE_SWAP=$ENABLE_SWAP, SWAP_SIZE_GB=$SWAP_SIZE_GB)"
fi

# ---------- 4) Current Ollama (native) with models on /ssd ----------
if ! command -v ollama >/dev/null 2>&1; then
  echo "[i] Installing current Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
fi
systemctl enable --now ollama

mkdir -p "$OLLAMA_MODELS_DIR"
chown -R ollama:ollama "$OLLAMA_MODELS_DIR" || true

# systemd drop-in for OLLAMA_MODELS
mkdir -p /etc/systemd/system/ollama.service.d
cat >/etc/systemd/system/ollama.service.d/override.conf <<EOF
[Service]
Environment=OLLAMA_MODELS=$OLLAMA_MODELS_DIR
EOF

systemctl daemon-reload
systemctl restart ollama

# ---------- 5) Current Open WebUI (Docker :main) with data on /ssd ----------
mkdir -p "$OPENWEBUI_DATA"
docker rm -f open-webui 2>/dev/null || true
docker pull ghcr.io/open-webui/open-webui:main
docker run -d --name open-webui --network host \
  -v "$OPENWEBUI_DATA:/app/backend/data" \
  -e OLLAMA_BASE_URL=http://127.0.0.1:11434 \
  --restart unless-stopped ghcr.io/open-webui/open-webui:main

# ---------- 6) Optional: tame unattended upgrades ----------
systemctl disable --now unattended-upgrades 2>/dev/null || true
systemctl disable --now apt-daily.service apt-daily.timer apt-daily-upgrade.service apt-daily-upgrade.timer 2>/dev/null || true

echo
echo "=== Done ==="
echo "SSD mount       : $SSD_MP  ($(df -h "$SSD_MP" | tail -1))"
echo "Docker Root Dir : $(docker info 2>/dev/null | awk -F': ' '/Docker Root Dir/{print $2}')"
echo "Ollama version  : $(ollama --version || true)"
echo "Ollama models   : $OLLAMA_MODELS_DIR"
echo "Open WebUI URL  : http://$(hostname -I | awk '{print $1}'):8080"
echo
echo "Swap summary:"
swapon --show || true
sysctl vm.swappiness || true
