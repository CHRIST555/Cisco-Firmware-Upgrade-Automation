# 🔧 Cisco IOS-XE Firmware Upgrade Automation

Ansible playbooks for automating end-to-end firmware upgrades on Cisco IOS-XE devices (tested on Catalyst 9000 series), driven by an interactive Python CLI launcher.

No file server. No config file editing. No vault setup. Drop your firmware files in the project folder and run the launcher.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Using the Launcher](#using-the-launcher)
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

Everything is driven through `upgrade_tool.py` — a terminal wizard that asks you a few questions and then runs Ansible.

---

## Project Structure

```
cisco-firmware-upgrade/
├── upgrade_tool.py                     # Interactive CLI launcher — start here
│
├── cat9k_iosxe.17.09.04a.SPA.bin      # ← drop your firmware image here
├── cat9k_iosxe.17.09.04a.SPA.bin.md5  # ← drop your MD5 file here
│
├── site_firmware_upgrade.yml           # Master playbook — imports all four phases
├── pre_upgrade_checks.yml              # Phase 1: readiness validation & config backup
├── stage_firmware.yml                  # Phase 2: direct file push & MD5 verification
├── execute_upgrade.yml                 # Phase 3: boot variable, reload, wait
├── post_upgrade_verify.yml             # Phase 4: version check & service health
│
├── group_vars/
│   └── ios_routers/
│       └── firmware.yml                # Safety thresholds (flash space, CPU limit)
│
├── inventory/
│   └── production.yml                  # Optional static host inventory
│
├── backups/
│   └── pre-upgrade/                    # Config backups written here during Phase 1
│
└── reports/
    ├── pre-upgrade/                    # Pre-upgrade state snapshots
    └── post-upgrade/                   # Per-device upgrade result reports
```

> All output directories (`backups/`, `reports/`) are created automatically on first run.

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
- Enough free flash space for the firmware image (~1 GB recommended headroom)

---

## Quick Start

**1. Clone the repository**

```bash
git clone https://github.com/your-org/cisco-firmware-upgrade.git
cd cisco-firmware-upgrade
```

**2. Download your firmware from Cisco's software page and drop both files into the project folder**

```
cisco-firmware-upgrade/
├── cat9k_iosxe.17.09.04a.SPA.bin
└── cat9k_iosxe.17.09.04a.SPA.bin.md5
```

The `.md5` file is available on the same Cisco download page as the `.bin`. Downloading both means you never have to type or copy a checksum manually.

**3. Run the launcher**

```bash
python upgrade_tool.py
```

That's it. The launcher handles everything else interactively.

---

## Using the Launcher

Run `python upgrade_tool.py` and follow the prompts. No flags or arguments needed.

### Step 1 — Firmware image

The launcher searches the project folder, `~/Downloads`, and `~/Desktop` for `.bin` files and lists them automatically. Select yours from the list.

```
  ℹ  Found 1 .bin file(s):
  [1] /root/cisco-firmware-upgrade/cat9k_iosxe.17.09.04a.SPA.bin  (847 MB)
  [2] Enter a custom path
```

It then looks for a matching `.md5` file in the same folder and reads the checksum automatically:

```
  ✔  MD5 loaded from cat9k_iosxe.17.09.04a.SPA.bin.md5: a1b2c3d4...f6a1
```

If no `.md5` file is found it will ask you to enter the checksum manually.

Next it asks for the target version string — this is auto-guessed from the filename so you usually just press Enter to confirm:

```
  ›  Target version [17.09.04a]:
```

### Step 2 — Select upgrade phase

```
  [1] ALL phases (full upgrade)
  [2] Phase 1 — Pre-upgrade checks only
  [3] Phase 2 — Stage firmware only
  [4] Phase 3 — Execute upgrade only
  [5] Phase 4 — Post-upgrade verify only
  [6] Phases 1 + 2 (checks + stage, no reload)
```

Pick `1` for a full upgrade. Use individual phases to re-run a specific step if something fails.

### Step 3 — SSH credentials

Enter your SSH username. The launcher scans `~/.ssh` and the project folder for SSH keys and lists them automatically — pick one or enter a custom path.

```
  ℹ  Found 1 SSH key(s):
  [1] /root/.ssh/cisco_upgrade
  [2] Enter a custom path
  [3] Skip — use password auth
```

### Step 4 — Device IP addresses

Type device IPs or hostnames one at a time. Give each one a friendly name or press Enter to accept the auto-generated alias.

```
  ›  Enter IP or hostname: 10.0.1.1
  ✔  Added: device-10-0-1-1  (10.0.1.1)

  ›  Enter IP or hostname: 10.0.1.2
  ✔  Added: device-10-0-1-2  (10.0.1.2)

  ›  Enter IP or hostname:        ← press Enter when done
```

### Step 5 — Review and confirm

A full summary is shown before anything runs:

```
  Phase    :  ALL phases (full upgrade)
  Username :  netadmin
  SSH Key  :  /root/.ssh/cisco_upgrade
  Firmware :  cat9k_iosxe.17.09.04a.SPA.bin  (847.2 MB)
  Version  :  17.09.04a
  MD5      :  a1b2c3d4...f6a1
  Dry run  :  no

  Target devices:
  #    Alias                IP Address
  ──────────────────────────────────────────────
  1.   core-rtr-01          10.0.1.1
  2.   core-rtr-02          10.0.1.2
```

Enter `y` to proceed or `n` to abort with no changes made.

---

## Running Playbooks Directly

You can bypass the launcher and call `ansible-playbook` directly. Pass firmware details as extra variables:

```bash
ansible-playbook site_firmware_upgrade.yml \
  -i inventory/production.yml \
  -u netadmin --private-key ~/.ssh/cisco_upgrade \
  -e "firmware_local_bin_path=/path/to/cat9k_iosxe.17.09.04a.SPA.bin" \
  -e "firmware_target_image=cat9k_iosxe.17.09.04a.SPA.bin" \
  -e "firmware_target_version=17.09.04a" \
  -e "firmware_target_md5=a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
```

Run a single phase using tags:

```bash
# Stage only
ansible-playbook site_firmware_upgrade.yml --tags stage [options]

# Verify only
ansible-playbook site_firmware_upgrade.yml --tags verify [options]
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
- Verifies MD5 hash on the device — **aborts immediately on mismatch**

`serial: 3` — three simultaneous transfers (reduce in `stage_firmware.yml` if your connection is slow).

### Phase 3 — Execute Upgrade

- Clears existing boot statements and sets the new image
- Confirms boot variable with `show boot` before reloading
- Saves configuration then reloads
- Waits up to 10 minutes for SSH to recover
- Pauses 60 s for routing protocols to stabilise

`serial: 1` — **one device reloaded at a time.**

### Phase 4 — Post-upgrade Verification

- Asserts running version matches target version
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
- **MD5 auto-read** — checksum loaded from `.md5` file, no manual copy-paste
- **MD5 verification on device** — image integrity confirmed before boot variable is touched
- **Pre-flight assertions** — flash space and CPU checked before any file is transferred
- **Boot variable confirmation** — `show boot` verified before reload is triggered
- **`serial: 1` on reload** — one device rebooted at a time
- **Idempotent staging** — existing flash images are reused, no unnecessary re-transfers
- **Auto directory creation** — all output folders created automatically on first run

---

## Troubleshooting

**Device does not come back after reload**
Increase `timeout` in the `wait_for` task in `execute_upgrade.yml` (default 600 s). Chassis platforms with many line cards can take longer to boot.

**MD5 mismatch after staging**
Delete the image on the device (`del flash:<image>`), verify the `.md5` file matches what Cisco published, and re-run Phase 2.

**Transfer times out**
Increase `ansible_command_timeout` in `stage_firmware.yml` (default 2700 s / 45 min). Large images over slow management-plane links can take a long time.

**Boot variable not accepted**
Some platforms use `flash0:` instead of `flash:`. Adjust the `boot system` line in `execute_upgrade.yml`.

**Wrong prompt order on reload**
The `Save?` / `Proceed with reload?` prompt order varies by IOS-XE version. If the reload task hangs, swap the `prompt`/`answer` entries in `execute_upgrade.yml`.

**Key file not found**
Make sure you enter the full path to the key file, or drop the key in the project folder — the launcher searches there automatically alongside `~/.ssh`.

---

## License

MIT — see [LICENSE](LICENSE) for details.
