#!/usr/bin/env python3
# =============================================================================
# upgrade_tool.py — Interactive Cisco Firmware Upgrade Launcher
# =============================================================================
# Walks you through:
#   1. Select which upgrade phase(s) to run
#   2. Enter SSH credentials (username + key file)
#   3. Select the firmware .bin file from your machine
#   4. Enter device IP addresses
#   5. Review and confirm — then Ansible runs
#
# Requirements:
#   pip install ansible
#   ansible-galaxy collection install cisco.ios ansible.netcommon
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
    print(c("  Ansible Automation Launcher  v2.0", DIM))
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

def numbered_menu(title, options):
    """Display a numbered menu and return the chosen index."""
    section(title)
    for i, opt in enumerate(options, 1):
        label = opt[0] if isinstance(opt, tuple) else opt
        desc  = opt[1] if isinstance(opt, tuple) and len(opt) > 1 else ""
        print(f"  {c(f'[{i}]', YELLOW)} {c(label, BOLD)}" +
              (f"\n       {c(desc, DIM)}" if desc else ""))
    print()
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
    ("ALL phases (full upgrade)",               "site_firmware_upgrade.yml", None),
    ("Phase 1 — Pre-upgrade checks only",       "site_firmware_upgrade.yml", "preflight,pre_upgrade"),
    ("Phase 2 — Stage firmware only",           "site_firmware_upgrade.yml", "stage"),
    ("Phase 3 — Execute upgrade only",          "site_firmware_upgrade.yml", "upgrade,reload"),
    ("Phase 4 — Post-upgrade verify only",      "site_firmware_upgrade.yml", "verify,post_upgrade"),
    ("Phases 1 + 2 (checks + stage, no reload)","site_firmware_upgrade.yml", "preflight,pre_upgrade,stage"),
]

# ── SSH credentials ──────────────────────────────────────────────────────────

def find_ssh_keys():
    """Return absolute paths to SSH private keys in ~/.ssh and the current directory."""
    candidates = []
    # Standard key names in ~/.ssh
    ssh_dir = Path.home() / ".ssh"
    if ssh_dir.exists():
        for pattern in ("id_rsa", "id_ed25519", "id_ecdsa", "*.pem", "*.key"):
            candidates.extend(ssh_dir.glob(pattern))
    # Also check current directory for keys (e.g. cagarc12_key dropped next to the tool)
    for pattern in ("*.key", "*.pem", "*_key"):
        candidates.extend(Path(".").glob(pattern))
    # Deduplicate and return absolute paths
    seen, result = set(), []
    for p in candidates:
        abs_p = str(p.resolve())
        if p.is_file() and abs_p not in seen:
            seen.add(abs_p)
            result.append(abs_p)
    return result

def collect_ssh_credentials():
    section("SSH Credentials")
    info("These are used to log into your Cisco devices.")
    print()

    username = prompt("SSH username", default=os.environ.get("USER", "admin"))

    keys     = find_ssh_keys()
    key_path = None

    if keys:
        info(f"Found {len(keys)} SSH key(s):")
        options = keys + ["Enter a custom path", "Skip — use password auth"]
        for i, k in enumerate(options, 1):
            print(f"  {c(f'[{i}]', YELLOW)} {k}")
        print()
        while True:
            raw = prompt("Select key number")
            try:
                idx = int(raw) - 1
                if idx == len(keys):
                    entered = prompt("Enter full path to SSH private key").strip()
                    key_path = str(Path(entered).resolve())
                elif idx == len(keys) + 1:
                    key_path = None   # password auth
                elif 0 <= idx < len(keys):
                    key_path = keys[idx]   # already absolute
                break
            except (ValueError, TypeError):
                error("Invalid choice.")
    else:
        warn("No SSH keys found automatically.")
        raw = prompt("Enter full path to SSH private key (or press Enter for password auth)")
        if raw:
            key_path = str(Path(raw.strip()).resolve())

    if key_path:
        if not Path(key_path).exists():
            warn(f"Key file not found: {key_path} — Ansible may fail.")
        else:
            success(f"Using key: {key_path}")
    else:
        info("No key selected — Ansible will prompt for a password per device.")

    return username, key_path

# ── Firmware file browser ────────────────────────────────────────────────────

def collect_firmware_file():
    section("Firmware Image")
    info("Select the .bin firmware file on this machine to push to devices.")
    print()

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
    # Deduplicate while preserving order
    seen = set()
    found_bins = [f for f in found_bins if not (f in seen or seen.add(f))]

    firmware_path = None

    if found_bins:
        info(f"Found {len(found_bins)} .bin file(s):")
        options = found_bins + ["Enter a custom path"]
        for i, f in enumerate(options, 1):
            size = ""
            if os.path.exists(f):
                mb   = os.path.getsize(f) / (1024 * 1024)
                size = c(f"  ({mb:.0f} MB)", DIM)
            print(f"  {c(f'[{i}]', YELLOW)} {f}{size}")
        print()
        while True:
            raw = prompt("Select firmware file number")
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
        firmware_path = prompt("Enter full path to firmware .bin file")
        if firmware_path:
            firmware_path = firmware_path.strip()

    if not firmware_path or not Path(firmware_path).exists():
        error(f"File not found: {firmware_path}")
        sys.exit(1)

    filename = Path(firmware_path).name
    size_mb  = os.path.getsize(firmware_path) / (1024 * 1024)
    success(f"Selected: {filename}  ({size_mb:.1f} MB)")
    return str(Path(firmware_path).resolve())   # Return absolute path

# ── IP address input & validation ────────────────────────────────────────────

def is_valid_ip(value):
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False

def is_valid_hostname(value):
    if len(value) > 253:
        return False
    allowed = re.compile(
        r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?"
        r"(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$"
    )
    return bool(allowed.match(value))

def resolve_hostname(host):
    try:
        return socket.gethostbyname(host)
    except socket.gaierror:
        return None

def collect_device_ips():
    section("Target Device IP Addresses")
    info("Enter the IP address or hostname of each device to upgrade.")
    info("Press Enter with no input when you are done.")
    print()

    devices = []

    while True:
        if devices:
            print(c("  Current device list:", CYAN))
            print(f"  {'#':<4} {'Alias':<25} {'IP Address'}")
            print(c("  " + "─" * 50, DIM))
            for i, d in enumerate(devices, 1):
                print(f"  {c(str(i)+'.', DIM):<4} {c(d['alias'], BOLD):<34} {c(d['ip'], YELLOW)}")
            print()

        raw = prompt(
            "Enter IP or hostname" + (" (or press Enter to finish)" if devices else "")
        )

        if not raw:
            if not devices:
                warn("At least one device is required.")
                continue
            break

        raw = raw.strip()

        if is_valid_ip(raw):
            ip    = raw
            alias = "device-" + raw.replace(".", "-").replace(":", "-")
            custom = prompt(f"Alias for {ip}", default=alias)
            alias  = custom.strip() if custom else alias
        elif is_valid_hostname(raw):
            alias    = raw
            resolved = resolve_hostname(raw)
            if resolved:
                success(f"Resolved {raw} → {resolved}")
                ip = resolved
            else:
                warn(f"Could not resolve '{raw}' — using as-is.")
                ip = raw
        else:
            error(f"'{raw}' is not a valid IP address or hostname.")
            continue

        if ip in [d["ip"] for d in devices]:
            warn(f"{ip} is already in the list — skipping.")
            continue

        devices.append({"alias": alias, "ip": ip})
        success(f"Added: {alias}  ({ip})")
        print()

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

# ── Dynamic inventory writer ─────────────────────────────────────────────────

def write_dynamic_inventory(devices, username, key_path):
    """Write a temporary Ansible inventory file and return its path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yml", prefix="ansible_inv_", delete=False
    )
    lines = [
        "# Auto-generated by upgrade_tool.py — deleted after run",
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

# ── Run options ──────────────────────────────────────────────────────────────

def collect_run_options():
    section("Run Options")
    check   = prompt("Dry run? (--check, no changes applied) (y/n)", default="n")
    verbose = prompt("Verbose output? (-v) (y/n)", default="n")
    return check.lower() == "y", verbose.lower() == "y"

# ── Directory scaffolding ────────────────────────────────────────────────────

def ensure_directories():
    """Create all directories the playbooks write output to."""
    required = [
        "backups/pre-upgrade",
        "reports/pre-upgrade",
        "reports/post-upgrade",
        "group_vars/ios_routers",
        "inventory",
    ]
    created = []
    for d in required:
        if not os.path.exists(d):
            os.makedirs(d)
            created.append(d)
    if created:
        section("Creating Output Directories")
        for d in created:
            success(f"Created: {d}/")

# ── Build ansible-playbook command ───────────────────────────────────────────

def build_command(phase_idx, inventory, username, key_path,
                  check, verbose, firmware_path):
    _, playbook, tags = PHASES[phase_idx]

    cmd = ["ansible-playbook", playbook, "-i", inventory, "-u", username]

    if key_path:
        cmd += ["--private-key", key_path]
    if tags:
        cmd += ["--tags", tags]
    if check:
        cmd += ["--check"]
    if verbose:
        cmd += ["-v"]

    # Pass the local firmware path and derived image name into the playbooks
    firmware_filename = Path(firmware_path).name
    cmd += ["-e", f"firmware_local_bin_path={firmware_path}"]
    cmd += ["-e", f"firmware_target_image={firmware_filename}"]

    return cmd

# ── Summary screen ───────────────────────────────────────────────────────────

def show_summary(phase_idx, username, key_path, firmware_path, devices, check, verbose, cmd):
    section("Summary — Review Before Running")
    phase_label = PHASES[phase_idx][0]
    print(f"  {c('Phase    :', CYAN)}  {phase_label}")
    print(f"  {c('Username :', CYAN)}  {username}")
    print(f"  {c('SSH Key  :', CYAN)}  {key_path or c('(password auth)', DIM)}")
    print(f"  {c('Firmware :', CYAN)}  {Path(firmware_path).name}  {c(f'({os.path.getsize(firmware_path)/1024/1024:.1f} MB)', DIM)}")
    print(f"  {c('Dry run  :', CYAN)}  {'yes (--check)' if check else 'no'}")
    print(f"  {c('Verbose  :', CYAN)}  {'yes' if verbose else 'no'}")
    print()
    print(f"  {c('Target devices:', CYAN)}")
    print(f"  {'#':<4} {'Alias':<25} {'IP Address'}")
    print(c("  " + "─" * 46, DIM))
    for i, d in enumerate(devices, 1):
        print(f"  {c(str(i)+'.', DIM):<4} {c(d['alias'], BOLD):<34} {c(d['ip'], YELLOW)}")
    print()
    # Build a clean display version of the command
    # Replace the temp inventory path with a readable label
    # Replace the full firmware path with just the filename
    display_cmd = []
    skip_next = False
    for i, a in enumerate(cmd):
        if skip_next:
            skip_next = False
            continue
        if a == "-i" and i + 1 < len(cmd) and cmd[i+1].startswith("/tmp/ansible_inv_"):
            display_cmd += ["-i", "<dynamic-inventory>"]
            skip_next = True
        elif a.startswith("firmware_local_bin_path="):
            display_cmd.append(f"firmware_local_bin_path={Path(firmware_path).name}")
        else:
            display_cmd.append(a)
    print(f"  {c('Command:', CYAN)}")
    wrapped = textwrap.fill(" ".join(display_cmd), width=58,
                            initial_indent="    ", subsequent_indent="      ")
    print(c(wrapped, BOLD))
    print()

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not shutil.which("ansible-playbook"):
        banner()
        error("ansible-playbook not found in PATH.")
        info("Install with:  pip install ansible")
        sys.exit(1)

    banner()

    # 1. Phase
    phase_idx = numbered_menu("Select Upgrade Phase", PHASES)

    # 2. SSH credentials
    username, key_path = collect_ssh_credentials()

    # 3. Firmware file — mandatory, exits if not found
    firmware_path = collect_firmware_file()

    # 4. Device IPs → dynamic inventory
    devices     = collect_device_ips()
    dynamic_inv = write_dynamic_inventory(devices, username, key_path)

    # 5. Run options
    check, verbose = collect_run_options()

    # 6. Build command
    cmd = build_command(phase_idx, dynamic_inv, username, key_path,
                        check, verbose, firmware_path)

    # 7. Summary + confirm
    banner()
    show_summary(phase_idx, username, key_path, firmware_path, devices, check, verbose, cmd)

    go = prompt("Proceed? (y/n)", default="y")
    if go.lower() != "y":
        warn("Aborted — no changes made.")
        os.unlink(dynamic_inv)
        sys.exit(0)

    # 8. Create output directories
    ensure_directories()

    # 9. Run Ansible
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
        if os.path.exists(dynamic_inv):
            os.unlink(dynamic_inv)

    print()

if __name__ == "__main__":
    main()
