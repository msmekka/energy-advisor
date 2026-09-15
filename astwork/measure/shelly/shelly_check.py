#!/usr/bin/env python3
"""Query the Shelly plug (validation-tier wall-power reading, cross-checked
against the RAPL baseline — never the primary measurement path).

    python3 shelly_check.py status
    python3 shelly_check.py sample --seconds 30
    python3 shelly_check.py sample --seconds 30 --out measurements/shelly_20260915.json

Uses the Gen2+ RPC HTTP API (this device is gen 4): GET requests to
/rpc/<Method>?param=value, no auth (device info shows auth_en: false).
Stdlib only — no requests/pandas dependency for a two-endpoint client.
"""
import argparse
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

SHELLY_DIR = Path(__file__).resolve().parent
DEVICE_INFO_PATH = SHELLY_DIR / "shelly-device-info.json"
DEFAULT_TIMEOUT_S = 5


def default_host() -> str:
    """Shelly devices advertise mDNS as <id>.local by default."""
    with open(DEVICE_INFO_PATH) as f:
        info = json.load(f)
    return f"{info['id']}.local"


def rpc_get(host: str, method: str, **params) -> dict:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"http://{host}/rpc/{method}"
    if query:
        url += f"?{query}"
    try:
        with urllib.request.urlopen(url, timeout=DEFAULT_TIMEOUT_S) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        raise SystemExit(f"error reaching Shelly at {host}: {e}") from e


def switch_status(host: str, switch_id: int = 0) -> dict:
    return rpc_get(host, "Switch.GetStatus", id=switch_id)


def cmd_status(args):
    status = switch_status(args.host, args.id)
    print(json.dumps(status, indent=2))


def cmd_sample(args):
    start = switch_status(args.host, args.id)
    t0 = time.monotonic()
    time.sleep(args.seconds)
    end = switch_status(args.host, args.id)
    elapsed = time.monotonic() - t0

    wh_start = start["aenergy"]["total"]
    wh_end = end["aenergy"]["total"]
    delta_wh = wh_end - wh_start
    if delta_wh < 0:
        # Switch.ResetCounters called by something else mid-sample.
        raise SystemExit(
            "aenergy.total went backwards — counters were reset during the "
            "sample window, discard this run"
        )

    energy_j = delta_wh * 3600.0
    avg_power_w = energy_j / elapsed

    record = {
        "source": "shelly",
        "device_id": start.get("id"),
        "requested_seconds": args.seconds,
        "elapsed_s": elapsed,
        "aenergy_wh_start": wh_start,
        "aenergy_wh_end": wh_end,
        "energy_j": energy_j,
        "avg_power_w": avg_power_w,
        "apower_w_start": start.get("apower"),
        "apower_w_end": end.get("apower"),
    }

    print(json.dumps(record, indent=2))

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(record, f, indent=2)
        print(f"written to {out_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        default=None,
        help="Shelly hostname/IP (default: <device id>.local from shelly-device-info.json)",
    )
    parser.add_argument("--id", type=int, default=0, help="switch component id (default 0)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="one-shot Switch.GetStatus dump")
    p_status.set_defaults(func=cmd_status)

    p_sample = sub.add_parser("sample", help="measure avg power over a window, via aenergy delta")
    p_sample.add_argument("--seconds", type=float, required=True)
    p_sample.add_argument("--out", default=None, help="write the record as JSON to this path")
    p_sample.set_defaults(func=cmd_sample)

    args = parser.parse_args()
    if args.host is None:
        args.host = default_host()
    args.func(args)


if __name__ == "__main__":
    main()
