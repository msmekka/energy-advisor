#!/usr/bin/env bash
# Pin CPU frequency/turbo/SMT for reproducible RAPL measurements, then
# capture an idle energy baseline to subtract from snippet measurements later.
#
#   sudo ./pin_baseline.sh                # pin, soak, capture baseline
#   sudo ./pin_baseline.sh --dry-run      # print what would happen, change nothing
#   sudo ./pin_baseline.sh --restore      # undo pinning, restart stopped services
#        ./pin_baseline.sh --status       # what is pinned right now (no root needed)
#
# This is the ONLY part of the measurement pipeline that needs root. It relaxes
# the RAPL counters to 0444 for the session so benchmark children can read them
# unprivileged; --restore puts every mode back exactly as it found it. A reboot
# is also a full restore -- sysfs modes, cpufreq, SMT and stopped services are
# all session state.
#
# Assumes Linux with intel_pstate (pyRAPL is Intel-only). Edit NOISY_SERVICES
# for your distro before the first real run — the list here is a conservative
# guess, not a verified fit for your install.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="/var/tmp/energy-advisor-pin.state"
SERVICES_FILE="${STATE_FILE}.services"
RAPL_MODES_FILE="${STATE_FILE}.rapl"
BASELINE_DIR="${BASELINE_DIR:-$SCRIPT_DIR/measurements}"
# Baselines are written here by root; campaign rows are written by the
# unprivileged runner and get their own tree. Separate producers, separate
# owners -- the runner never needs write access to a root-owned directory.
RUNS_DIR="${RUNS_DIR:-$SCRIPT_DIR/runs}"
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

log() { echo "[pin $(date '+%Y-%m-%dT%H:%M:%S%z')] $*"; }
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
read_file() {
  # read_file <path> — prints the file's contents on stdout, retrying on
  # transient EBUSY. cpufreq attribute *reads* use the same trylock-on-the-
  # policy-rwsem mechanism as writes, so a plain `cat` right after an SMT
  # sibling offline can fail exactly like a write would — and under
  # set -Eeuo pipefail, an unguarded failure here kills the whole script.
  local path="$1" attempt out
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if out="$(cat "$path" 2>/dev/null)"; then
      printf '%s' "$out"
      return 0
    fi
    sleep 0.3
  done
  return 1
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

rapl_attr_paths() {
  # One path per RAPL attribute the reader needs, symlinks resolved. The zone
  # hierarchy is at most two levels (package -> subzone), so this globs both
  # explicitly rather than using `find -L`, which can wander into each device
  # directory's "subsystem" backlink and loop forever. Caller pipes to sort -u;
  # the same zone appears at both levels on some kernels.
  local zone attr
  for zone in /sys/class/powercap/intel-rapl*/ /sys/class/powercap/intel-rapl*/intel-rapl*/; do
    [[ -d "$zone" ]] || continue
    for attr in energy_uj name max_energy_range_uj; do
      [[ -e "$zone$attr" ]] || continue
      readlink -f "$zone$attr" 2>/dev/null || true
    done
  done
}

relax_rapl() {
  # energy_uj is commonly 0400 (PLATYPUS / CVE-2020-8694). Relaxing it to 0444
  # for the session is what keeps the campaign unprivileged: children read the
  # counters directly and no benchmark process ever gets root. name and
  # max_energy_range_uj go along too -- discover_domains() reads all three, and
  # an unreadable name raises out of the walk rather than being skipped.
  #
  # The original mode of every file is recorded, not assumed: restoring to a
  # guessed 0400 would be worse than not restoring at all.
  local path mode
  [[ "$DRY_RUN" -eq 1 ]] || : > "$RAPL_MODES_FILE"
  while read -r path; do
    [[ -n "$path" ]] || continue
    mode="$(stat -c '%a' "$path" 2>/dev/null)" || continue
    if [[ "$DRY_RUN" -eq 1 ]]; then
      log "(dry-run) would chmod 0$mode -> 0444  $path"
    else
      printf '%s %s\n' "$mode" "$path" >> "$RAPL_MODES_FILE"
      chmod 0444 "$path" && log "relaxed 0$mode -> 0444  $path"
    fi
  done < <(rapl_attr_paths | sort -u)

  if [[ "$DRY_RUN" -eq 0 && ! -s "$RAPL_MODES_FILE" ]]; then
    echo "error: no RAPL attribute files found under /sys/class/powercap -- is this an Intel box with intel_rapl loaded?" >&2
    exit 1
  fi
}

verify_rapl_readable() {
  # chmod can report success and still leave the counters unreadable to the
  # campaign user. Catch that here, in the first second, rather than at run 1
  # of a campaign on the far side of a ${SOAK_SECONDS}s soak.
  local user="${SUDO_USER:-}" probe
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "(dry-run) would verify an energy_uj read as ${user:-<SUDO_USER unset>}"
    return
  fi
  if [[ -z "$user" || "$user" == "root" ]]; then
    log "warning: SUDO_USER unset (invoked as root directly) -- cannot verify the unprivileged read; check it by hand as the campaign user"
    return
  fi
  probe="$(rapl_attr_paths | grep -m1 '/energy_uj$' || true)"
  if [[ -z "$probe" ]]; then
    echo "error: no energy_uj found to verify" >&2
    exit 1
  fi
  if sudo -u "$user" cat "$probe" >/dev/null 2>&1; then
    log "verified: $user can read $probe"
  else
    echo "error: $user still cannot read $probe after chmod -- aborting before the soak" >&2
    exit 1
  fi
}

ensure_runs_dir() {
  local user="${SUDO_USER:-}"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "(dry-run) would create $RUNS_DIR owned by ${user:-<SUDO_USER unset>}"
    return
  fi
  mkdir -p "$RUNS_DIR"
  if [[ -n "$user" && "$user" != "root" ]]; then
    chown "$user:$(id -gn "$user")" "$RUNS_DIR" && log "runs dir $RUNS_DIR owned by $user"
  fi
}

restore_rapl_modes() {
  # Best-effort per file. sysfs attributes are recreated with default modes on
  # reboot, so a path that is gone is not an error -- the kernel already did
  # the restore.
  [[ -f "$RAPL_MODES_FILE" ]] || return 0
  local mode path
  while read -r mode path; do
    [[ -n "$mode" && -n "$path" ]] || continue
    if [[ ! -e "$path" ]]; then
      log "skipped (gone, likely rebooted): $path"
      continue
    fi
    if [[ "$DRY_RUN" -eq 1 ]]; then
      log "(dry-run) would chmod 0$mode  $path"
    else
      chmod "$mode" "$path" 2>/dev/null && log "restored 0$mode  $path"
    fi
  done < "$RAPL_MODES_FILE"
  [[ "$DRY_RUN" -eq 1 ]] || rm -f "$RAPL_MODES_FILE"
}

on_premature_exit() {
  # Pinning is a sequence of partial state changes. Dying halfway through -- a
  # failed write, Ctrl-C during the soak, SIGTERM -- would otherwise leave the
  # rig turbo-disabled, SMT-off, counters world-readable and services stopped,
  # with no run to show for it. Disarm first so a failure inside the rollback
  # cannot re-enter here.
  local rc=$?
  trap - ERR INT TERM
  log "premature exit (status $rc) during pin -- rolling back rather than leaving the rig half-pinned"
  restore || log "warning: rollback itself failed -- run --status, then --restore by hand"
  exit "$rc"
}

status() {
  # Answers "is this rig still pinned?" without root, so a crashed campaign
  # needs no archaeology to recover from.
  local path mode want
  if [[ -f "$STATE_FILE" ]]; then
    log "state file present: $STATE_FILE (pinned, or a pin run was interrupted)"
    sed 's/^/    /' "$STATE_FILE"
  else
    log "no state file at $STATE_FILE -- nothing recorded as pinned"
  fi
  [[ -f /sys/devices/system/cpu/intel_pstate/no_turbo ]] && \
    log "no_turbo now: $(cat /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null || echo '?')"
  [[ -f /sys/devices/system/cpu/smt/control ]] && \
    log "SMT now: $(cat /sys/devices/system/cpu/smt/control 2>/dev/null || echo '?')"
  log "cpu0 governor now: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo '?')"
  if [[ -f "$RAPL_MODES_FILE" ]]; then
    while read -r want path; do
      [[ -n "$path" ]] || continue
      mode="$(stat -c '%a' "$path" 2>/dev/null || echo 'gone')"
      log "rapl $path: now 0$mode, original 0$want"
    done < "$RAPL_MODES_FILE"
  else
    log "no recorded RAPL mode changes"
  fi
  if [[ -n "${SUDO_USER:-}" || $EUID -ne 0 ]]; then
    local probe
    probe="$(rapl_attr_paths | grep -m1 '/energy_uj$' || true)"
    if [[ -n "$probe" ]]; then
      if [[ $EUID -ne 0 ]] && cat "$probe" >/dev/null 2>&1; then
        log "this user CAN read $probe -- a campaign would run"
      elif [[ $EUID -ne 0 ]]; then
        log "this user CANNOT read $probe -- a campaign would fail at run 1"
      fi
    fi
  fi
  log "a reboot restores all of the above; nothing here survives one"
}

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "error: run with sudo" >&2
    exit 1
  fi
}

pin() {
  local turbo_orig_val smt_orig_val governor_orig_val minfreq_orig_val maxfreq_orig_val base_freq
  [[ "$DRY_RUN" -eq 1 ]] || : > "$STATE_FILE"

  # Armed for the whole pinning sequence, disarmed only once the baseline is
  # captured. Everything from here to that point is rolled back on any
  # premature exit.
  [[ "$DRY_RUN" -eq 1 ]] || trap on_premature_exit ERR INT TERM

  # RAPL permissions first: the cheapest step, and the one most likely to
  # reveal that this rig cannot support an unprivileged campaign at all. Better
  # to learn that in the first second than after a ${SOAK_SECONDS}s soak.
  relax_rapl
  verify_rapl_readable
  ensure_runs_dir

  # --- Noisy services (stopped first — thermald etc. actively rewrite
  # cpufreq policy attributes and will contend with the writes below if
  # they're still running when we get to them) ---
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

  # --- Turbo ---
  if [[ -f /sys/devices/system/cpu/intel_pstate/no_turbo ]]; then
    turbo_orig_val="$(read_file /sys/devices/system/cpu/intel_pstate/no_turbo)" || {
      echo "error: could not read current turbo state after retries — aborting before any writes" >&2; exit 1; }
    record_orig "turbo_path=/sys/devices/system/cpu/intel_pstate/no_turbo" "turbo_path"
    record_orig "turbo_orig=$turbo_orig_val" "turbo_orig"
    write_file /sys/devices/system/cpu/intel_pstate/no_turbo 1 "turbo disabled (intel_pstate)"
  elif [[ -f /sys/devices/system/cpu/cpufreq/boost ]]; then
    turbo_orig_val="$(read_file /sys/devices/system/cpu/cpufreq/boost)" || {
      echo "error: could not read current boost state after retries — aborting before any writes" >&2; exit 1; }
    record_orig "turbo_path=/sys/devices/system/cpu/cpufreq/boost" "turbo_path"
    record_orig "turbo_orig=$turbo_orig_val" "turbo_orig"
    write_file /sys/devices/system/cpu/cpufreq/boost 0 "turbo/boost disabled (generic cpufreq)"
  else
    log "warning: no turbo control found (checked intel_pstate/cpufreq boost) — skipping"
  fi

  # --- SMT ---
  if [[ -f /sys/devices/system/cpu/smt/control ]]; then
    smt_orig_val="$(read_file /sys/devices/system/cpu/smt/control)" || {
      echo "error: could not read current SMT state after retries — aborting before any writes" >&2; exit 1; }
    record_orig "smt_orig=$smt_orig_val" "smt_orig"
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
      governor_orig_val="$(read_file "$cpu/cpufreq/scaling_governor")" || {
        echo "error: could not read current governor for $cpu after retries — aborting before any writes" >&2; exit 1; }
      minfreq_orig_val="$(read_file "$cpu/cpufreq/scaling_min_freq")" || {
        echo "error: could not read current min_freq for $cpu after retries — aborting before any writes" >&2; exit 1; }
      maxfreq_orig_val="$(read_file "$cpu/cpufreq/scaling_max_freq")" || {
        echo "error: could not read current max_freq for $cpu after retries — aborting before any writes" >&2; exit 1; }
      record_orig "governor_orig=$governor_orig_val" "governor_orig"
      record_orig "minfreq_orig=$minfreq_orig_val" "minfreq_orig"
      record_orig "maxfreq_orig=$maxfreq_orig_val" "maxfreq_orig"
      governor_saved=1
    fi

    if [[ -f "$cpu/cpufreq/base_frequency" ]]; then
      if base_freq="$(read_file "$cpu/cpufreq/base_frequency")"; then
        write_file "$cpu/cpufreq/scaling_governor" performance "$cpu governor=performance"
        # max first, then min — writing min before max can be rejected if the
        # new min would exceed the *current* max.
        write_file "$cpu/cpufreq/scaling_max_freq" "$base_freq" "$cpu max_freq -> $base_freq (base clock)"
        write_file "$cpu/cpufreq/scaling_min_freq" "$base_freq" "$cpu min_freq -> $base_freq (base clock)"
      else
        write_file "$cpu/cpufreq/scaling_governor" performance "$cpu governor=performance"
        log "warning: $cpu base_frequency unreadable after retries (busy) — performance governor only, frequency not hard-locked for this cpu"
      fi
    else
      write_file "$cpu/cpufreq/scaling_governor" performance "$cpu governor=performance"
      log "warning: $cpu has no base_frequency file — turbo-disable + performance governor only, frequency not hard-locked. Verify with 'cat $cpu/cpufreq/scaling_cur_freq' under load."
    fi
  done

  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "(dry-run) would sleep ${SOAK_SECONDS}s for thermal soak, then capture ${SAMPLE_SECONDS}s idle baseline"
    return
  fi

  log "thermal soak: sleeping ${SOAK_SECONDS}s before baseline capture"
  sleep "$SOAK_SECONDS"

  capture_baseline

  # Pinning completed. From here the pinned state is meant to persist for the
  # campaign, so a later exit must NOT roll it back.
  trap - ERR INT TERM
  log "rig pinned and ready. Campaign runs unprivileged; use --status to check, --restore when done."
}

capture_baseline() {
  mkdir -p "$BASELINE_DIR"
  local out="$BASELINE_DIR/idle_baseline_$(date +%Y%m%dT%H%M%S).json"
  log "capturing ${SAMPLE_SECONDS}s idle RAPL baseline -> $out"
  python3 "$SCRIPT_DIR/rapl.py" --seconds "$SAMPLE_SECONDS" --out "$out"
  log "baseline written to $out — subtract avg_power_w[domain] * snippet_duration_s from each snippet's energy_uj[domain]"
}

restore() {
  if [[ ! -f "$STATE_FILE" ]]; then
    log "no state file at $STATE_FILE — nothing to restore"
    restore_rapl_modes
    return 0
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

  restore_rapl_modes

  [[ "$DRY_RUN" -eq 1 ]] || rm -f "$STATE_FILE"
  log "restore complete"
}

main() {
  local mode="pin"
  for arg in "$@"; do
    case "$arg" in
      --dry-run) DRY_RUN=1 ;;
      --restore) mode="restore" ;;
      --status) mode="status" ;;
      *) echo "usage: $0 [--restore] [--status] [--dry-run]" >&2; exit 1 ;;
    esac
  done

  # --status only reads, so it works as the campaign user -- which is the
  # point: it also reports whether THAT user can read the counters.
  if [[ "$mode" == "status" ]]; then status; exit 0; fi

  [[ "$DRY_RUN" -eq 1 ]] || require_root
  if [[ "$mode" == "restore" ]]; then restore; else pin; fi
}

main "$@"
