#!/usr/bin/env python3
"""Interactive client for the Minecraft control service."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
SERVER_URL = ""
AUTH_TOKEN = ""
POLL_SECONDS = 3.0


def load_config(path: Path) -> None:
    global SERVER_URL, AUTH_TOKEN, POLL_SECONDS
    with path.open("r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    SERVER_URL = config["server_url"].rstrip("/")
    AUTH_TOKEN = config["auth_token"]
    POLL_SECONDS = float(config.get("poll_seconds", 3))


def api_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"X-Auth-Token": AUTH_TOKEN}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{SERVER_URL}{path}", data=data, headers=headers, method=method
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"ok": False, "error": f"HTTP {exc.code}: {raw}"}
    except (OSError, urllib.error.URLError) as exc:
        return {"ok": False, "error": str(exc)}


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def choose_server(servers: list[dict[str, Any]]) -> dict[str, Any]:
    print("Available Minecraft servers:\n")
    for index, server in enumerate(servers, start=1):
        print(f"{index}. {server['friendly_name']} [{server['state']}]")

    while True:
        choice = input("\nSelect server number: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(servers):
            return servers[int(choice) - 1]
        print("Enter one of the listed numbers.")


def request_status(server_id: str) -> dict[str, Any]:
    encoded = urllib.parse.quote(server_id, safe="")
    return api_request("GET", f"/api/status/{encoded}")


def format_uptime(seconds: int) -> str:
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def monitor_server(server: dict[str, Any]) -> None:
    server_id = server["id"]
    shutdown_requested = False

    while True:
        try:
            response = request_status(server_id)
            if not response.get("ok"):
                clear_screen()
                print(f"Status error: {response.get('error', response)}")
                time.sleep(POLL_SECONDS)
                continue

            status = response["status"]
            clear_screen()
            print(f"Minecraft Server: {status['friendly_name']} ({server_id})")
            print(f"State: {status['state']}")
            print(f"PID: {status.get('pid') or 'n/a'}")
            print(f"Uptime: {format_uptime(status.get('uptime_seconds', 0))}")
            print("-" * 70)
            print("\n".join(status.get("recent_log", [])))
            print("-" * 70)

            if status["state"] in ("stopped", "offline"):
                print("Server is no longer running.")
                return
            if shutdown_requested:
                print("Shutdown requested. Press Ctrl+C again to force terminate.")
            else:
                print("Press Ctrl+C to request graceful shutdown.")
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            force = shutdown_requested
            shutdown_requested = True
            action = "force termination" if force else "graceful shutdown"
            print(f"\nRequesting {action}...")
            try:
                response = api_request(
                    "POST", "/api/stop", {"server": server_id, "force": force}
                )
            except KeyboardInterrupt:
                print("\nSecond interrupt received; requesting force termination...")
                response = api_request(
                    "POST", "/api/stop", {"server": server_id, "force": True}
                )
            print(response.get("message", response.get("error", response)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Minecraft control client")
    parser.add_argument(
        "--config",
        type=Path,
        default=BASE_DIR / "client_config.json",
        help="Path to client configuration JSON",
    )
    args = parser.parse_args()

    try:
        load_config(args.config.resolve())
        response = api_request("GET", "/api/servers")
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "Failed to fetch server list"))
        if not response["servers"]:
            print("No Minecraft servers are configured on the host.")
            return

        selected = choose_server(response["servers"])
        if selected["state"] in ("running", "stopping", "force-stopping"):
            print(f"\n{selected['friendly_name']} is already active; attaching monitor.")
        else:
            print(f"\nRequesting startup for {selected['friendly_name']}...")
            response = api_request("POST", "/api/start", {"server": selected["id"]})
            if not response.get("ok"):
                raise RuntimeError(response.get("message", response.get("error", response)))
            print(response["message"])
            time.sleep(1)
        monitor_server(selected)
    except KeyboardInterrupt:
        print("\nExiting client.")
    except (KeyError, OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
