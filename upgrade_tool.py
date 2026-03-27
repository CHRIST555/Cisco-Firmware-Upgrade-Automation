#!/usr/bin/env python3
# =============================================================================
# upgrade_tool.py — Interactive Cisco Firmware Upgrade Launcher
# =============================================================================
# Presents a terminal UI to:
#   1. Select which upgrade phase(s) to run
#   2. Configure SSH credentials (username + key file)
#   3. Browse and select the firmware .bin file
#   4. Optionally limit to specific devices
#   5. Build and execute the correct ansible-playbook command
#
# Requirements:
#   pip install ansible                  (for ansible-playbook)
#   pip install paramiko                 (optional: SSH key validation)
#
# Usage:
#   python upgrade_tool.py
# =============================================================================

import os
import sys
import subprocess
import glob
import shutil
import textwrap
import ipaddress
import socket
import re
from pathlib import Path
from getpass import getpass
import tempfile

# ── Terminal colour helpers ──────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
WHITE  = "\033[97m"
BLUE   = "\033[94m"

def c(text, *codes):
    return "".join(codes) + str(text) + RESET

def banner():
    os.system("clear" if os.name != "nt" else "cls")
    width = 64
    print(c("═" * width, CYAN))
    print(c("  ██████╗ ██╗███████╗ ██████╗ ██████╗ ", CYAN))
    print(c("  ██╔════╝██║██╔════╝██╔════╝██╔═══██╗", CYAN))
    print(c("  ██║     ██║███████╗██║     ██║   ██║", CYAN))
    print(c("  ██║     ██║╚════██║██║     ██║   ██║", CYAN))
    print(c("  ╚██████╗██║███████║╚██████╗╚██████╔╝", CYAN))
    print(c("   ╚═════╝╚═╝╚══════╝ ╚═════╝ ╚═════╝ ", CYAN))
    print()
    print(c("  Cisco IOS-XE Firmware Upgrade Tool", BOLD + WHITE))
    print(c("  Ansible Automation Launcher  v1.1", DIM))
    print(c("═" * width, CYAN))
    print()

def section(title):
    print()
    print(c(f"  ┌─ {title} ", CYAN) + c("─" * max(0, 56 - len(title)), CYAN))

def info(msg):
    print(c("  ℹ  ", CYAN) + msg)

def success(msg):
    print(c("  ✔  ", GREEN) + msg)

def warn(msg):
    print(c("  ⚠  ", YELLOW) + msg)

def error(msg):
    print(c("  ✖  ", RED) + msg)

def prompt(msg, default=None):
    suffix = f" [{c(default, DIM)}]" if default else ""
    val = input(c("  ›  ", CYAN) + msg + suffix + " ").strip()
    return val if val else default

def numbered_menu(title, options, multi=False):
    """Display a numbered menu. Returns index (single) or list of indices (multi)."""
    section(title)
    for i, opt in enumerate(options, 1):
        label = opt if isinstance(opt, str) else opt[0]
        desc  = "" if isinstance(opt, str) else opt[1]
        num   = c(f"  [{i}]", YELLOW)
        print(f"{num} {c(label, BOLD)}" + (f"\n       {c(desc, DIM)}" if desc else ""))
    print()

    if multi:
        raw = prompt("Enter numbers separated by commas (e.g. 1,3) or press Enter for ALL")
        if not raw:
            return list(range(len(options)))
        chosen = []
        for part in raw.split(","):
            try:
                idx = int(part.strip()) - 1
                if 0 <= idx < len(options):
                    chosen.append(idx)
            except ValueError:
                pass
        return chosen if chosen else list(range(len(options)))
    else:
        while True:
            raw = prompt("Enter number")
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(options):
                    return idx
            except (ValueError, TypeError):
                pass
            error("Invalid choice — try again.")

# ── Phase definitions ────────────────────────────────────────────────────────

PHASES = [
    ("ALL phases (full upgrade)",          "site_firmware_upgrade.yml",  None),
    ("Phase 1 — Pre-upgrade checks only",  "site_firmware_upgrade.yml",  "preflight,pre_upgrade"),
    ("Phase 2 — Stage firmware only",      "site_firmware_upgrade.yml",  "stage"),
    ("Phase 3 — Execute upgrade only",     "site_firmware_upgrade.yml",  "upgrade,reload"),
    ("Phase 4 — Post-upgrade verify only", "site_firmware_upgrade.yml",  "verify,post_upgrade"),
    ("Phases 1 + 2 (check + stage, no reload)", "site_firmware_upgrade.yml", "preflight,pre_upgrade,stage"),
]

# ── SSH credential helpers ───────────────────────────────────────────────────

def find_ssh_keys():
    """Return a list of likely SSH private key paths on this machine."""
    candidates = []
    ssh_dir = Path.home() / ".ssh"
    if ssh_dir.exists():
        for pattern in ("id_rsa", "id_ed25519", "id_ecdsa", "*.pem", "*.key"):
            candidates.extend(ssh_dir.glob(pattern))
    return [str(p) for p in candidates if p.is_file()]

def collect_ssh_credentials():
    section("SSH Credentials")
    info("These credentials will be passed to Ansible for device login.")
    print()

    username = prompt("SSH username", default=os.environ.get("USER", "admin"))

    # Key file selection
    keys = find_ssh_keys()
    key_path = None

    if keys:
        info(f"Found {len(keys)} SSH key(s) in ~/.ssh:")
        key_options = keys + ["Enter a custom path"]
        for i, k in enumerate(key_options, 1):
            print(f"  {c(f'[{i}]', YELLOW)} {k}")
        print()
        while True:
            raw = prompt("Select key number or press Enter to skip (password auth)")
            if not raw:
                break
            try:
                idx = int(raw) - 1
                if idx == len(keys):
                    key_path = prompt("Enter full path to SSH private key")
                elif 0 <= idx < len(keys):
                    key_path = keys[idx]
                break
            except (ValueError, TypeError):
                error("Invalid choice.")
    else:
        warn("No SSH keys found in ~/.ssh.")
        raw = prompt("Enter full path to SSH private key (or press Enter to use password auth)")
        if raw:
            key_path = raw.strip()

    if key_path:
        if not Path(key_path).exists():
            warn(f"Key file not found: {key_path}  — Ansible may fail.")
        else:
            success(f"Using key: {key_path}")

    vault_pass = None
    print()
    info("Ansible Vault password is needed to decrypt firmware credentials.")
    use_vault = prompt("Use Ansible Vault? (y/n)", default="y")
    if use_vault.lower() == "y":
        vault_pass = getpass("  ›  Vault password (hidden): ")

    return username, key_path, vault_pass

# ── Firmware file browser ────────────────────────────────────────────────────

def collect_firmware_file():
    section("Firmware Image Selection")
    info("Select the .bin firmware image to use for this upgrade campaign.")
    print()

    # Search common locations
    search_dirs = [
        ".",
        "./firmware",
        str(Path.home() / "Downloads"),
        str(Path.home() / "firmware"),
        "/tmp",
    ]

    found_bins = []
    for d in search_dirs:
        found_bins.extend(glob.glob(os.path.join(d, "*.bin")))

    firmware_path = None

    if found_bins:
        info(f"Found {len(found_bins)} .bin file(s):")
        options = found_bins + ["Enter a custom path"]
        for i, f in enumerate(options, 1):
            size = ""
            if os.path.exists(f):
                mb = os.path.getsize(f) / (1024 * 1024)
                size = c(f"  ({mb:.0f} MB)", DIM)
            print(f"  {c(f'[{i}]', YELLOW)} {f}{size}")
        print()

        while True:
            raw = prompt("Select firmware file number (or press Enter to skip)")
            if not raw:
                break
            try:
                idx = int(raw) - 1
                if idx == len(found_bins):
                    firmware_path = prompt("Enter full path to .bin file")
                elif 0 <= idx < len(found_bins):
                    firmware_path = found_bins[idx]
                break
            except (ValueError, TypeError):
                error("Invalid choice.")
    else:
        warn("No .bin files found in common locations.")
        firmware_path = prompt("Enter full path to firmware .bin file (or press Enter to skip)")
        if firmware_path:
            firmware_path = firmware_path.strip()

    if firmware_path:
        if not Path(firmware_path).exists():
            warn(f"File not found: {firmware_path}")
            firmware_path = None
        else:
            filename = Path(firmware_path).name
            size_mb  = os.path.getsize(firmware_path) / (1024 * 1024)
            success(f"Selected: {filename}  ({size_mb:.1f} MB)")
            info("Make sure firmware.yml target_image matches this filename.")

    return firmware_path

# ── IP address input & validation ────────────────────────────────────────────

def is_valid_ip(value):
    """Return True if value is a valid IPv4 or IPv6 address."""
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False

def is_valid_hostname(value):
    """Return True if value looks like a valid hostname (basic check)."""
    if len(value) > 253:
        return False
    allowed = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$")
    return bool(allowed.match(value))

def resolve_hostname(host):
    """Try to resolve a hostname to an IP for display purposes."""
    try:
        return socket.gethostbyname(host)
    except socket.gaierror:
        return None

def collect_device_ips():
    """
    Interactive prompt to build a list of (hostname/alias, ip_address) tuples.
    Returns the list plus a flag indicating whether a dynamic inventory was built.
    """
    section("Target Device IP Addresses")
    info("Enter the IP addresses (or hostnames) of devices to upgrade.")
    info("Press Enter with no input when done. Minimum 1 device required.")
    print()

    devices = []   # list of {"alias": str, "ip": str}

    while True:
        # Show current list
        if devices:
            print(c("  Current device list:", CYAN))
            print(f"  {'#':<4} {'Alias/Hostname':<25} {'IP Address'}", )
            print(c("  " + "─" * 52, DIM))
            for i, d in enumerate(devices, 1):
                alias_col = c(d["alias"], BOLD)
                ip_col    = c(d["ip"], YELLOW) if d["ip"] != d["alias"] else c("(direct)", DIM)
                print(f"  {c(str(i)+'.',DIM):<4} {alias_col:<34} {ip_col}")
            print()

        # Prompt for next IP
        raw = prompt(
            f"Enter IP address or hostname (or press Enter to finish{', add more' if devices else ''})"
        )

        if not raw:
            if not devices:
                warn("At least one device is required.")
                continue
            break

        raw = raw.strip()

        # Validate
        if is_valid_ip(raw):
            ip     = raw
            # Auto-generate a friendly alias: replace dots/colons with dashes
            alias  = "device-" + raw.replace(".", "-").replace(":", "-")
            # Let user optionally name it
            custom = prompt(f"Alias/hostname for {ip} (press Enter for '{alias}')", default=alias)
            alias  = custom.strip() if custom else alias
        elif is_valid_hostname(raw):
            alias   = raw
            resolved = resolve_hostname(raw)
            if resolved:
                success(f"Resolved {raw} → {resolved}")
                ip = resolved
            else:
                warn(f"Could not resolve '{raw}' — will use it as-is (ensure DNS works from devices).")
                ip = raw
        else:
            error(f"'{raw}' is not a valid IP address or hostname. Try again.")
            continue

        # Check for duplicates
        existing_ips = [d["ip"] for d in devices]
        if ip in existing_ips:
            warn(f"{ip} is already in the list — skipping.")
            continue

        devices.append({"alias": alias, "ip": ip})
        success(f"Added: {alias}  ({ip})")
        print()

        # After each addition, offer quick removal
        if len(devices) > 1:
            remove = prompt("Remove a device by number? (press Enter to continue)")
            if remove:
                try:
                    idx = int(remove.strip()) - 1
                    if 0 <= idx < len(devices):
                        removed = devices.pop(idx)
                        warn(f"Removed: {removed['alias']}  ({removed['ip']})")
                except (ValueError, TypeError):
                    pass

    return devices


def write_dynamic_inventory(devices, username, key_path):
    """
    Write a temporary Ansible inventory YAML file from the device list.
    Returns the path to the temp file (caller must delete it).

    Generated structure:
        all:
          children:
            upgrade_candidates:
              hosts:
                <alias>:
                  ansible_host: <ip>
                  ansible_user: <username>
                  ansible_ssh_private_key_file: <key>   # if provided
                  ansible_network_os: ios
                  ansible_connection: network_cli
    """
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yml", prefix="ansible_inv_", delete=False
    )

    lines = [
        "# Auto-generated inventory — created by upgrade_tool.py",
        "# This file is deleted automatically after the playbook run.",
        "---",
        "all:",
        "  children:",
        "    upgrade_candidates:",
        "      hosts:",
    ]

    for d in devices:
        lines.append(f"        {d['alias']}:")
        lines.append(f"          ansible_host: {d['ip']}")
        lines.append(f"          ansible_user: {username}")
        lines.append( "          ansible_network_os: ios")
        lines.append( "          ansible_connection: network_cli")
        if key_path:
            lines.append(f"          ansible_ssh_private_key_file: {key_path}")

    tmp.write("\n".join(lines) + "\n")
    tmp.close()
    os.chmod(tmp.name, 0o600)
    return tmp.name


# ── Inventory / host limit ───────────────────────────────────────────────────

def collect_inventory_options(username, key_path):
    """
    Offer two paths:
      A) Enter IPs now → write a dynamic inventory temp file
      B) Use an existing inventory file on disk
    Returns (inventory_path, limit_string, devices_list, dynamic_inv_path)
    dynamic_inv_path is set only when we wrote a temp file (so main() can delete it).
    """
    section("Inventory & Target Devices")

    print(f"  {c('[1]', YELLOW)} {c('Enter device IP addresses now', BOLD)}")
    print(f"       {c('Type in IPs interactively — a temporary inventory is generated', DIM)}")
    print(f"  {c('[2]', YELLOW)} {c('Use an existing inventory file', BOLD)}")
    print(f"       {c('Point to your own hosts.yml / production.yml', DIM)}")
    print()

    while True:
        choice = prompt("Select option", default="1")
        if choice in ("1", "2"):
            break
        error("Enter 1 or 2.")

    devices       = []
    dynamic_inv   = None
    limit         = None

    if choice == "1":
        # ── Dynamic: collect IPs and write temp inventory ──────────────────
        devices     = collect_device_ips()
        dynamic_inv = write_dynamic_inventory(devices, username, key_path)
        inventory   = dynamic_inv
        success(f"Temporary inventory written: {dynamic_inv}")
        info(f"{len(devices)} device(s) added to upgrade_candidates group.")

    else:
        # ── Existing file ──────────────────────────────────────────────────
        inv_candidates = (
            glob.glob("inventory/*.yml") +
            glob.glob("inventory/*.yaml") +
            glob.glob("inventory/*.ini") +
            glob.glob("hosts") +
            glob.glob("hosts.yml")
        )

        inventory = "inventory/production.yml"   # sensible default
        if inv_candidates:
            info("Available inventory files:")
            for i, f in enumerate(inv_candidates, 1):
                print(f"  {c(f'[{i}]', YELLOW)} {f}")
            print(f"  {c('[Enter]', DIM)} Use default: {inventory}")
            print()
            raw = prompt("Select inventory file")
            if raw:
                try:
                    idx = int(raw) - 1
                    if 0 <= idx < len(inv_candidates):
                        inventory = inv_candidates[idx]
                except (ValueError, TypeError):
                    pass
        else:
            custom = prompt("Path to inventory file", default=inventory)
            inventory = custom

        limit = prompt("Limit to specific hosts? (comma-separated, or press Enter for ALL)")
        limit = limit.strip() if limit else None

    return inventory, limit, devices, dynamic_inv

# ── Dry-run option ───────────────────────────────────────────────────────────

def collect_run_options():
    section("Run Options")
    check = prompt("Dry run only? (--check, no changes applied) (y/n)", default="n")
    verbose = prompt("Verbose output? (-v) (y/n)", default="n")
    return check.lower() == "y", verbose.lower() == "y"

# ── Build and display the command ────────────────────────────────────────────

def build_command(phase_idx, inventory, username, key_path,
                  vault_pass, limit, check, verbose, firmware_path):
    _, playbook, tags = PHASES[phase_idx]

    cmd = ["ansible-playbook", playbook, "-i", inventory]

    # SSH user
    cmd += ["-u", username]

    # SSH key
    if key_path:
        cmd += ["--private-key", key_path]

    # Tags
    if tags:
        cmd += ["--tags", tags]

    # Limit
    if limit:
        cmd += ["--limit", limit]

    # Check mode
    if check:
        cmd += ["--check"]

    # Verbose
    if verbose:
        cmd += ["-v"]

    # Extra vars — pass firmware image filename if user selected one
    extra_vars = {}
    if firmware_path:
        extra_vars["firmware_override_image"] = Path(firmware_path).name

    if extra_vars:
        ev_str = " ".join(f"{k}={v}" for k, v in extra_vars.items())
        cmd += ["-e", ev_str]

    return cmd

def write_vault_pass_file(vault_pass):
    """Write vault password to a temp file so it isn't visible in ps output."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".vp", delete=False)
    tmp.write(vault_pass)
    tmp.close()
    os.chmod(tmp.name, 0o600)
    return tmp.name

# ── Confirmation summary ─────────────────────────────────────────────────────

def show_summary(phase_idx, inventory, username, key_path,
                 vault_pass, limit, check, verbose, firmware_path, devices, cmd):
    section("Summary — Review Before Running")
    phase_label = PHASES[phase_idx][0]
    print(f"  {c('Phase      :', CYAN)}  {phase_label}")
    print(f"  {c('Inventory  :', CYAN)}  {inventory}")
    print(f"  {c('Username   :', CYAN)}  {username}")
    print(f"  {c('SSH Key    :', CYAN)}  {key_path or c('(password auth)', DIM)}")
    print(f"  {c('Vault      :', CYAN)}  {'✔ configured' if vault_pass else c('✖ not set', YELLOW)}")
    print(f"  {c('Limit      :', CYAN)}  {limit or c('ALL hosts', DIM)}")
    print(f"  {c('Firmware   :', CYAN)}  {Path(firmware_path).name if firmware_path else c('use firmware.yml value', DIM)}")
    print(f"  {c('Dry run    :', CYAN)}  {'yes (--check)' if check else 'no'}")
    print(f"  {c('Verbose    :', CYAN)}  {'yes' if verbose else 'no'}")

    # Show device table if IPs were entered manually
    if devices:
        print()
        print(f"  {c('Target devices:', CYAN)}")
        print(f"  {'#':<4} {'Alias':<25} {'IP Address'}")
        print(c("  " + "─" * 46, DIM))
        for i, d in enumerate(devices, 1):
            print(f"  {c(str(i)+'.',DIM):<4} {c(d['alias'], BOLD):<34} {c(d['ip'], YELLOW)}")

    print()
    # Show command (mask vault pass file path for cleanliness)
    display_cmd = [a for a in cmd if not a.endswith(".vp") and not a.startswith("/tmp/ansible_inv_")]
    if vault_pass:
        display_cmd += ["--vault-password-file", "<temp-file>"]
    if devices:
        display_cmd += ["-i", "<dynamic-inventory>"]
    print(f"  {c('Command:', CYAN)}")
    wrapped = textwrap.fill(" ".join(display_cmd), width=58,
                            initial_indent="    ", subsequent_indent="      ")
    print(c(wrapped, BOLD))
    print()

# ── Main flow ────────────────────────────────────────────────────────────────

def main():
    # Check ansible-playbook is available
    if not shutil.which("ansible-playbook"):
        banner()
        error("ansible-playbook not found in PATH.")
        info("Install with:  pip install ansible")
        sys.exit(1)

    banner()

    # 1. Phase selection
    phase_idx = numbered_menu(
        "Select Upgrade Phase",
        [(p[0], "") for p in PHASES]
    )

    # 2. SSH credentials
    username, key_path, vault_pass = collect_ssh_credentials()

    # 3. Firmware file
    firmware_path = collect_firmware_file()

    # 4. Inventory + host limit (passes username & key so dynamic inv can embed them)
    inventory, limit, devices, dynamic_inv = collect_inventory_options(username, key_path)

    # 5. Run options
    check, verbose = collect_run_options()

    # 6. Build command
    cmd = build_command(phase_idx, inventory, username, key_path,
                        vault_pass, limit, check, verbose, firmware_path)

    vault_file = None
    if vault_pass:
        vault_file = write_vault_pass_file(vault_pass)
        cmd += ["--vault-password-file", vault_file]

    # 7. Summary + confirm
    banner()
    show_summary(phase_idx, inventory, username, key_path,
                 vault_pass, limit, check, verbose, firmware_path, devices, cmd)

    go = prompt("Proceed? (y/n)", default="y")
    if go.lower() != "y":
        warn("Aborted — no changes made.")
        if vault_file:
            os.unlink(vault_file)
        if dynamic_inv and os.path.exists(dynamic_inv):
            os.unlink(dynamic_inv)
        sys.exit(0)

    # 8. Run
    section("Running Ansible")
    print()
    try:
        result = subprocess.run(cmd, check=False)
        print()
        if result.returncode == 0:
            success("Ansible playbook completed successfully.")
        else:
            error(f"Ansible exited with code {result.returncode}.")
            info("Review the output above for task failures.")
    except KeyboardInterrupt:
        print()
        warn("Interrupted by user.")
    finally:
        # Always clean up temp files
        if vault_file and os.path.exists(vault_file):
            os.unlink(vault_file)
        if dynamic_inv and os.path.exists(dynamic_inv):
            os.unlink(dynamic_inv)

    print()

if __name__ == "__main__":
    main()
