# 🔧 Cisco IOS-XE Firmware Upgrade Automation

Ansible playbooks for automating end-to-end firmware upgrades on Cisco IOS-XE devices (tested on Catalyst 9000 series), driven by an interactive Python CLI launcher.

No file server needed. The launcher pushes the firmware image directly from your machine to each device over SSH.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Using the Launcher](#using-the-launcher)
- [Configuration](#configuration)
- [Running Playbooks Directly](#running-playbooks-directly)
- [Upgrade Phases](#upgrade-phases)
- [Output Files](#output-files)
- [Safety Features](#safety-features)
- [Troubleshooting](#troubleshooting)

---

## Overview

This project automates the full lifecycle of a Cisco firmware upgrade across four phases:

1. **Pre-flight checks** — validates version, free flash space, and CPU health; skips devices already on the target release; backs up running config
2. **Image staging** — pushes the firmware `.bin` file directly from your machine to each device's flash over SSH, then verifies MD5 integrity
3. **Upgrade execution** — sets the boot variable, saves config, reloads the device, and waits for it to recover
4. **Post-upgrade verification** — confirms the correct version booted, checks interface and routing protocol state, and writes a per-device report

Everything is driven through `upgrade_tool.py` — a terminal wizard that asks you five questions and then runs Ansible.

---

## Project Structure

```
.
├── upgrade_tool.py                # Interactive CLI launcher — start here
├── site_firmware_upgrade.yml      # Master playbook — imports all four phases
├── pre_upgrade_checks.yml         # Phase 1: readiness validation & config backup
├── stage_firmware.yml             # Phase 2: direct file push & MD5 verification
├── execute_upgrade.yml            # Phase 3: boot variable, reload, wait
├── post_upgrade_verify.yml        # Phase 4: version check & service health
│
├── group_vars/
│   └── ios_routers/
│       └── firmware.yml           # Image name, version, MD5, safety thresholds
│
├── inventory/
│   └── production.yml             # Optional static host inventory
│
├── backups/
│   └── pre-upgrade/               # Config backups written here during Phase 1
│
└── reports/
    ├── pre-upgrade/               # Pre-upgrade state snapshots
    └── post-upgrade/              # Per-device upgrade result reports
```

> All output directories are created automatically the first time you run `upgrade_tool.py`.

---

## Requirements

### Control Node (your machine)

| Requirement | Version |
|---|---|
| Python | ≥ 3.9 |
| Ansible | ≥ 2.14 |
| `cisco.ios` collection | ≥ 4.6 |
| `ansible.netcommon` collection | ≥ 5.0 |

```bash
pip install ansible
ansible-galaxy collection install cisco.ios ansible.netcommon
```

### Network Devices

- Cisco IOS-XE (Catalyst 9000 series recommended)
- SSH access from your machine to the device management interfaces
- Enough free flash space for the firmware image (~1 GB recommended)

### Firmware file

Just have the `.bin` file somewhere on your machine — `~/Downloads` or the project folder both work. The launcher will find it automatically.

---

## Quick Start

**1. Clone the repository**

```bash
git clone https://github.com/your-org/cisco-firmware-upgrade.git
cd cisco-firmware-upgrade
```

**2. Update the firmware details**

Edit `group_vars/ios_routers/firmware.yml` with the version string and MD5 hash for the image you are deploying. Both values are published on Cisco's software download page.

```yaml
firmware:
  target_version: "17.09.04a"
  target_image:   "cat9k_iosxe.17.09.04a.SPA.bin"
  target_md5:     "a1b2c3d4e5f6..."
```

**3. Run the launcher**

```bash
python upgrade_tool.py
```

That's it. The launcher handles everything else interactively.

---

## Using the Launcher

Run `python upgrade_tool.py` and follow the prompts — no flags or arguments needed.

### Step 1 — Select upgrade phase

```
  [1] ALL phases (full upgrade)
  [2] Phase 1 — Pre-upgrade checks only
  [3] Phase 2 — Stage firmware only
  [4] Phase 3 — Execute upgrade only
  [5] Phase 4 — Post-upgrade verify only
  [6] Phases 1 + 2 (checks + stage, no reload)
```

Pick `1` for a full upgrade. Use individual phases to re-run a specific step if something fails.

### Step 2 — SSH credentials

Enter your SSH username and select an SSH key. The launcher scans `~/.ssh` automatically and lists any keys it finds. If you don't use key-based auth, skip the key and Ansible will prompt for a password per device.

### Step 3 — Firmware file

The launcher searches your current directory, `~/Downloads`, and `~/firmware` for `.bin` files and lists them with their sizes. Pick one or type a custom path.

```
  ℹ  Found 1 .bin file(s):
  [1] /home/user/Downloads/cat9k_iosxe.17.09.04a.SPA.bin  (847 MB)
  [2] Enter a custom path
```

### Step 4 — Device IP addresses

Type device IPs or hostnames one at a time. Hostnames are resolved automatically. Give each device a friendly alias if you want (e.g. `core-rtr-01`), or press Enter to accept the auto-generated one.

```
  ›  Enter IP or hostname: 10.0.1.1
  ✔  Added: device-10-0-1-1  (10.0.1.1)

  ›  Enter IP or hostname: 10.0.1.2
  ✔  Added: device-10-0-1-2  (10.0.1.2)

  ›  Enter IP or hostname:        ← press Enter when done
```

### Step 5 — Review and confirm

The launcher shows a full summary before anything runs:

```
  Phase    :  ALL phases (full upgrade)
  Username :  netadmin
  SSH Key  :  /home/user/.ssh/id_ed25519
  Firmware :  cat9k_iosxe.17.09.04a.SPA.bin  (847.2 MB)
  Dry run  :  no

  Target devices:
  #    Alias                IP Address
  ──────────────────────────────────────────────
  1.   core-rtr-01          10.0.1.1
  2.   core-rtr-02          10.0.1.2
```

Enter `y` to proceed or `n` to abort with no changes made.

---

## Configuration

The only file you need to edit is `group_vars/ios_routers/firmware.yml`:

```yaml
firmware:
  target_version: "17.09.04a"                        # Must match 'show version' exactly
  target_image:   "cat9k_iosxe.17.09.04a.SPA.bin"   # Exact .bin filename
  target_md5:     "a1b2c3d4e5f6..."                  # MD5 from Cisco software portal

  # Safety thresholds — pre-upgrade checks abort if these are not met
  min_flash_space: 1000000000   # Free flash required in bytes (~1 GB)
  cpu_threshold:   80           # Max 5-minute CPU % before aborting
```

`local_bin_path` is filled in automatically by the launcher. You only need to set it manually if running playbooks directly (see below).

No passwords, no vault setup, no file server configuration needed.

---

## Running Playbooks Directly

You can bypass the launcher and call `ansible-playbook` directly. You will need to pass the firmware file path as an extra variable:

```bash
# Full upgrade
ansible-playbook site_firmware_upgrade.yml \
  -i inventory/production.yml \
  -u netadmin --private-key ~/.ssh/id_ed25519 \
  -e "firmware_local_bin_path=/path/to/cat9k_iosxe.17.09.04a.SPA.bin"

# Stage only
ansible-playbook site_firmware_upgrade.yml \
  -i inventory/production.yml \
  --tags stage \
  -e "firmware_local_bin_path=/path/to/cat9k_iosxe.17.09.04a.SPA.bin"

# Limit to specific devices
ansible-playbook site_firmware_upgrade.yml \
  -i inventory/production.yml \
  --limit "core-rtr-01,core-rtr-02" \
  -e "firmware_local_bin_path=/path/to/cat9k_iosxe.17.09.04a.SPA.bin"
```

| Tag | Phase |
|---|---|
| `preflight`, `pre_upgrade` | Phase 1 — Pre-upgrade checks |
| `stage` | Phase 2 — Image staging |
| `upgrade`, `reload` | Phase 3 — Execute upgrade |
| `verify`, `post_upgrade` | Phase 4 — Post-upgrade verification |

---

## Upgrade Phases

### Phase 1 — Pre-upgrade Checks

| Check | Pass condition |
|---|---|
| Current version | Not already running target version |
| Free flash space | > `min_flash_space` bytes (~1 GB) |
| CPU utilisation | < `cpu_threshold` % (5-minute average) |

Devices already on the target version are skipped automatically. A full config backup and state snapshot are saved before any changes.

`serial: 1` — one device at a time.

### Phase 2 — Stage Firmware

- Checks if the image is already on flash — skips transfer if it is (idempotent)
- Pushes the `.bin` file directly from your machine to device flash over SSH — no file server needed
- Verifies MD5 hash — **aborts immediately on mismatch**

`serial: 3` — three simultaneous transfers (reduce if your connection is slow).

### Phase 3 — Execute Upgrade

- Clears existing boot statements and sets the new image
- Confirms boot variable with `show boot` before reloading
- Saves configuration, then reloads
- Waits up to 10 minutes for SSH to recover
- Pauses 60 s for routing protocols to stabilise

`serial: 1` — **one device reloaded at a time.**

### Phase 4 — Post-upgrade Verification

- Asserts running version matches `target_version`
- Captures interface status and OSPF/BGP neighbour state
- Writes a full upgrade report per device to `reports/post-upgrade/`

---

## Output Files

| Path | Contents |
|---|---|
| `backups/pre-upgrade/<host>_<version>.cfg` | Full running-config backup |
| `reports/pre-upgrade/<host>.yml` | Version, flash space, CPU snapshot |
| `reports/post-upgrade/<host>.txt` | Version confirmed, interfaces, routing state |

---

## Safety Features

- **Nothing runs without confirmation** — full summary shown before Ansible starts
- **MD5 verification** — image integrity confirmed before boot variable is ever touched
- **Pre-flight assertions** — flash space and CPU checked before any file is transferred
- **Boot variable confirmation** — `show boot` checked before reload is triggered
- **`serial: 1` on reload** — one device rebooted at a time
- **Idempotent staging** — existing flash images are reused, no re-transfers
- **Auto directory creation** — all output folders created automatically on first run

---

## Troubleshooting

**Device does not come back after reload**
Increase `timeout` in the `wait_for` task in `execute_upgrade.yml` (default 600 s). Chassis platforms with many line cards can take longer to boot.

**MD5 mismatch after staging**
Delete the image on the device (`del flash:<image>`), verify `target_md5` in `firmware.yml` against Cisco's published value, and re-run Phase 2.

**Transfer times out**
Increase `ansible_command_timeout` in `stage_firmware.yml` (default 2700 s / 45 min). Transfers over slow management-plane links can take a long time for large images.

**Boot variable not accepted**
Some platforms use `flash0:` instead of `flash:`. Adjust the `boot system` line in `execute_upgrade.yml`.

**Wrong prompt order on reload**
The `Save?` / `Proceed with reload?` prompt order varies by IOS-XE version. If the reload task hangs, swap the `prompt`/`answer` entries in `execute_upgrade.yml`.

---

## License

MIT — see [LICENSE](LICENSE) for details.
