#!/usr/bin/env bash
# Pin CPU frequency/turbo/SMT for reproducible RAPL measurements, then
# capture an idle energy baseline to subtract from snippet measurements later.
#
#   sudo ./pin_baseline.sh                # pin, soak, capture baseline
#   sudo ./pin_baseline.sh --dry-run      # print what would happen, change nothing
#   sudo ./pin_baseline.sh --restore      # undo pinning, restart stopped services
#
# Assumes Linux with intel_pstate (pyRAPL is Intel-only). Edit NOISY_SERVICES
# for your distro before the first real run — the list here is a conservative
# guess, not a verified fit for your install.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="/var/tmp/energy-advisor-pin.state"
SERVICES_FILE="${STATE_FILE}.services"
BASELINE_DIR="${BASELINE_DIR:-$SCRIPT_DIR/measurements}"
SOAK_SECONDS="${SOAK_SECONDS:-600}"     # thermal soak before capturing baseline
SAMPLE_SECONDS="${SAMPLE_SECONDS:-30}"  # idle RAPL sample window
DRY_RUN=0

# Conservative default. Confirm each exists on your distro before relying on
# this — `systemctl is-active --quiet` no-ops safely for units that don't.
NOISY_SERVICES=(
  # Power/thermal daemons first — these actively rewrite cpufreq policy
  # attributes on a timer and will contend with (or silently undo) the
  # governor/turbo/frequency pinning below. Confirmed on rc-mw01: thermald
  # --adaptive holds the policy rwsem long enough to make our writes report
  # EBUSY with no corresponding hotplug event in dmesg.
  thermald
  tlp
  power-profiles-daemon
  auto-cpufreq
  cpupower
  bluetooth
  cups
  cups-browsed
  ModemManager
  avahi-daemon
  packagekit
  snapd.refresh.timer
  unattended-upgrades
  fwupd
  tracker-extract-3
  tracker-miner-fs-3
)

log() { echo "[pin] $*"; }
run() {
  # run <description> -- <command...>  — respects DRY_RUN
  local desc="$1"; shift
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "(dry-run) would: $desc"
  else
    "$@"
    log "$desc"
  fi
}
write_file() {
  # write_file <path> <value> <description> — respects DRY_RUN
  # Retries on transient EBUSY: offlining an SMT sibling triggers a kernel-side
  # cpufreq policy rebuild on its still-online partner core, and a governor/
  # freq write that lands mid-rebuild returns EBUSY for a few hundred ms.
  local path="$1" value="$2" desc="$3"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "(dry-run) would write '$value' -> $path  ($desc)"
    return
  fi
  local attempt
  for attempt in 1 2 3 4 5; do
    if echo "$value" > "$path" 2>/dev/null; then
      log "$desc"
      return
    fi
    sleep 0.3
  done
  log "warning: failed to write '$value' -> $path after 5 attempts ($desc) — not aborting; check 'cat $path' and its policy siblings by hand"
}
record_orig() {
  # record_orig <line> <description> — appends to STATE_FILE, skipped under DRY_RUN
  local line="$1" desc="$2"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "(dry-run) would record original state for restore: $desc"
  else
    echo "$line" >> "$STATE_FILE"
  fi
}

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "error: run with sudo" >&2
    exit 1
  fi
}

pin() {
  [[ "$DRY_RUN" -eq 1 ]] || : > "$STATE_FILE"

  # --- Turbo ---
  if [[ -f /sys/devices/system/cpu/intel_pstate/no_turbo ]]; then
    record_orig "turbo_path=/sys/devices/system/cpu/intel_pstate/no_turbo" "turbo_path"
    record_orig "turbo_orig=$(cat /sys/devices/system/cpu/intel_pstate/no_turbo)" "turbo_orig"
    write_file /sys/devices/system/cpu/intel_pstate/no_turbo 1 "turbo disabled (intel_pstate)"
  elif [[ -f /sys/devices/system/cpu/cpufreq/boost ]]; then
    record_orig "turbo_path=/sys/devices/system/cpu/cpufreq/boost" "turbo_path"
    record_orig "turbo_orig=$(cat /sys/devices/system/cpu/cpufreq/boost)" "turbo_orig"
    write_file /sys/devices/system/cpu/cpufreq/boost 0 "turbo/boost disabled (generic cpufreq)"
  else
    log "warning: no turbo control found (checked intel_pstate/cpufreq boost) — skipping"
  fi

  # --- SMT ---
  if [[ -f /sys/devices/system/cpu/smt/control ]]; then
    record_orig "smt_orig=$(cat /sys/devices/system/cpu/smt/control)" "smt_orig"
    write_file /sys/devices/system/cpu/smt/control off "SMT disabled"
    if [[ "$DRY_RUN" -eq 0 ]]; then
      log "settling 2s for sibling-offline cpufreq policy rebuild"
      sleep 2
    fi
  else
    log "warning: no /sys/devices/system/cpu/smt/control — skipping SMT disable"
  fi

  # --- Governor + frequency lock to base clock ---
  local governor_saved=0
  for cpu in /sys/devices/system/cpu/cpu[0-9]*; do
    [[ -f "$cpu/cpufreq/scaling_governor" ]] || continue

    if [[ "$governor_saved" -eq 0 ]]; then
      record_orig "governor_orig=$(cat "$cpu/cpufreq/scaling_governor")" "governor_orig"
      record_orig "minfreq_orig=$(cat "$cpu/cpufreq/scaling_min_freq")" "minfreq_orig"
      record_orig "maxfreq_orig=$(cat "$cpu/cpufreq/scaling_max_freq")" "maxfreq_orig"
      governor_saved=1
    fi

    if [[ -f "$cpu/cpufreq/base_frequency" ]]; then
      base_freq="$(cat "$cpu/cpufreq/base_frequency")"
      write_file "$cpu/cpufreq/scaling_governor" performance "$cpu governor=performance"
      # max first, then min — writing min before max can be rejected if the
      # new min would exceed the *current* max.
      write_file "$cpu/cpufreq/scaling_max_freq" "$base_freq" "$cpu max_freq -> $base_freq (base clock)"
      write_file "$cpu/cpufreq/scaling_min_freq" "$base_freq" "$cpu min_freq -> $base_freq (base clock)"
    else
      write_file "$cpu/cpufreq/scaling_governor" performance "$cpu governor=performance"
      log "warning: $cpu has no base_frequency file — turbo-disable + performance governor only, frequency not hard-locked. Verify with 'cat $cpu/cpufreq/scaling_cur_freq' under load."
    fi
  done

  # --- Noisy services ---
  [[ "$DRY_RUN" -eq 1 ]] || : > "$SERVICES_FILE"
  for svc in "${NOISY_SERVICES[@]}"; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
      if [[ "$DRY_RUN" -eq 1 ]]; then
        log "(dry-run) would stop: $svc"
      else
        echo "$svc" >> "$SERVICES_FILE"
        systemctl stop "$svc" 2>/dev/null && log "stopped $svc"
      fi
    fi
  done

  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "(dry-run) would sleep ${SOAK_SECONDS}s for thermal soak, then capture ${SAMPLE_SECONDS}s idle baseline"
    return
  fi

  log "thermal soak: sleeping ${SOAK_SECONDS}s before baseline capture"
  sleep "$SOAK_SECONDS"

  capture_baseline
}

capture_baseline() {
  mkdir -p "$BASELINE_DIR"
  local out="$BASELINE_DIR/idle_baseline_$(date +%Y%m%dT%H%M%S).json"
  log "capturing ${SAMPLE_SECONDS}s idle RAPL baseline -> $out"
  python3 - "$SAMPLE_SECONDS" "$out" <<'PY'
import sys, os, time, json

# Read /sys/class/powercap/intel-rapl* directly instead of pyRAPL: pyRAPL's
# DeviceAPIFactory only builds PkgAPI/DramAPI, and _get_socket_directory_names
# filters top-level zones to ones whose name contains "package" — so a
# sibling "psys" zone is skipped, and there's no CoreAPI/UncoreAPI at all.
# Walking sysfs ourselves picks up whatever domains this rig actually has
# (dram, psys, core, uncore, package-0, ...).

RAPL_ROOT = "/sys/class/powercap"
seconds = float(sys.argv[1])
out_path = sys.argv[2]


def discover_domains():
    domains = {}
    for root, _dirs, files in os.walk(RAPL_ROOT):
        if "energy_uj" not in files or "name" not in files:
            continue
        with open(os.path.join(root, "name")) as f:
            name = f.read().strip()
        max_range = None
        max_range_path = os.path.join(root, "max_energy_range_uj")
        if os.path.exists(max_range_path):
            with open(max_range_path) as f:
                max_range = int(f.read().strip())
        key = name
        n = 1
        while key in domains:
            n += 1
            key = f"{name}-{n}"
        domains[key] = {"path": root, "max_range_uj": max_range}
    return domains


def read_uj(path):
    with open(os.path.join(path, "energy_uj")) as f:
        return int(f.read().strip())


domains = discover_domains()
if not domains:
    print(f"no RAPL domains found under {RAPL_ROOT}", file=sys.stderr)
    sys.exit(1)

start = {k: read_uj(v["path"]) for k, v in domains.items()}
time.sleep(seconds)
end = {k: read_uj(v["path"]) for k, v in domains.items()}

energy_uj = {}
for k, v in domains.items():
    delta = end[k] - start[k]
    if delta < 0 and v["max_range_uj"]:  # 32-bit counter wraparound
        delta += v["max_range_uj"]
    energy_uj[k] = delta

record = {
    "duration_s": seconds,
    "energy_uj": energy_uj,
    "avg_power_w": {k: (uj / 1e6) / seconds for k, uj in energy_uj.items()},
}
with open(out_path, "w") as f:
    json.dump(record, f, indent=2)
print(json.dumps(record, indent=2))
PY
  log "baseline written to $out — subtract avg_power_w[domain] * snippet_duration_s from each snippet's energy_uj[domain]"
}

restore() {
  if [[ ! -f "$STATE_FILE" ]]; then
    log "no state file at $STATE_FILE — nothing to restore"
    exit 0
  fi
  # shellcheck disable=SC1090
  source "$STATE_FILE"

  if [[ -n "${turbo_path:-}" ]]; then
    write_file "$turbo_path" "$turbo_orig" "turbo restored: $turbo_path -> $turbo_orig"
  fi

  if [[ -n "${smt_orig:-}" ]]; then
    write_file /sys/devices/system/cpu/smt/control "$smt_orig" "SMT restored: $smt_orig"
  fi

  if [[ -n "${governor_orig:-}" ]]; then
    for cpu in /sys/devices/system/cpu/cpu[0-9]*; do
      [[ -f "$cpu/cpufreq/scaling_governor" ]] || continue
      write_file "$cpu/cpufreq/scaling_max_freq" "$maxfreq_orig" "$cpu max_freq restored"
      write_file "$cpu/cpufreq/scaling_min_freq" "$minfreq_orig" "$cpu min_freq restored"
      write_file "$cpu/cpufreq/scaling_governor" "$governor_orig" "$cpu governor restored: $governor_orig"
    done
  fi

  if [[ -f "$SERVICES_FILE" ]]; then
    while read -r svc; do
      [[ -n "$svc" ]] || continue
      if [[ "$DRY_RUN" -eq 1 ]]; then
        log "(dry-run) would restart: $svc"
      else
        systemctl start "$svc" 2>/dev/null && log "restarted $svc"
      fi
    done < "$SERVICES_FILE"
    [[ "$DRY_RUN" -eq 1 ]] || rm -f "$SERVICES_FILE"
  fi

  [[ "$DRY_RUN" -eq 1 ]] || rm -f "$STATE_FILE"
  log "restore complete"
}

main() {
  local mode="pin"
  for arg in "$@"; do
    case "$arg" in
      --dry-run) DRY_RUN=1 ;;
      --restore) mode="restore" ;;
      *) echo "usage: $0 [--restore] [--dry-run]" >&2; exit 1 ;;
    esac
  done

  [[ "$DRY_RUN" -eq 1 ]] || require_root
  if [[ "$mode" == "restore" ]]; then restore; else pin; fi
}

main "$@"
