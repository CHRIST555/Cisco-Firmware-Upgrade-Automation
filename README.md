# 🔧 Cisco Firmware Upgrade Automation

Ansible playbooks for automating end-to-end firmware upgrades on Cisco switches, driven by an interactive Python CLI launcher.

**Supported platforms:** Cisco IOS-XE (Catalyst) and Cisco CBS (Business Switch)

No file server. No config file editing. No vault setup. Drop your firmware files in the project folder and run the launcher — it handles everything else.

---

## 📋 Table of Contents

- [Overview](#overview)
- [How It Works](#how-it-works)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Using the Launcher](#using-the-launcher)
- [Upgrade Phases](#upgrade-phases)
- [Staging Without Rebooting](#staging-without-rebooting)
- [Output Files](#output-files)
- [Safety Features](#safety-features)
- [Running Playbooks Directly](#running-playbooks-directly)
- [Troubleshooting](#troubleshooting)

---

## Overview

This project automates the full lifecycle of a Cisco firmware upgrade across four phases:

1. **Pre-flight checks** — detects platform, validates version, checks free flash space and CPU health, backs up running config. Skips devices already on the target version entirely.
2. **Image staging** — pushes the firmware `.bin` file directly from your machine to each device's flash over SSH, then verifies MD5 integrity.
3. **Upgrade execution** — sets the boot variable, saves config, reloads the device, and waits for it to recover. **This phase reboots the device.**
4. **Post-upgrade verification** — confirms the correct version booted, checks interface and routing state, writes a per-device report.

---

## How It Works

Each playbook automatically detects whether it is talking to an IOS-XE (Catalyst) or CBS (Business Switch) device and runs the correct commands for that platform. You do not need separate playbooks or inventories for different switch types — mixed environments are handled automatically.

If a device is **already running the target version**, all four phases skip it completely. No connection is made beyond reading the version, and nothing is changed.

The firmware image is pushed **directly from your machine** to the device over the existing SSH connection — no separate file server or infrastructure needed.

**Phase 3 reboots the device.** If you want to stage the image in advance and reboot separately during a maintenance window, use the *Phases 1 + 2* option in the launcher.

---

## Project Structure

```
cisco-firmware-upgrade/
├── upgrade_tool.py                     # Interactive CLI launcher — start here
│
├── cat9k_iosxe.17.09.04a.SPA.bin      # ← drop your firmware .bin file here
├── cat9k_iosxe.17.09.04a.SPA.bin.md5  # ← drop your .md5 checksum file here
│
├── site_firmware_upgrade.yml           # Master playbook — runs all four phases
├── pre_upgrade_checks.yml              # Phase 1: platform detect, validation, backup
├── stage_firmware.yml                  # Phase 2: file transfer & MD5 verification
├── execute_upgrade.yml                 # Phase 3: set boot image, reload, wait
├── post_upgrade_verify.yml             # Phase 4: confirm version, service health
│
├── group_vars/
│   └── ios_routers/
│       └── firmware.yml                # Safety thresholds (flash space, CPU limit)
│
├── inventory/
│   └── production.yml                  # Optional static host inventory
│
├── backups/
│   └── pre-upgrade/                    # Config backups written here (auto-created)
│
└── reports/
    ├── pre-upgrade/                    # Pre-upgrade snapshots (auto-created)
    └── post-upgrade/                   # Upgrade result reports (auto-created)
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

- Cisco IOS-XE (Catalyst 9000 series) or Cisco CBS (CBS250 / CBS350 series)
- SSH access from your machine to the device management interfaces
- Enough free flash space for the firmware image (~1 GB recommended headroom)

---

## Quick Start

**1. Clone the repository**

```bash
git clone https://github.com/your-org/cisco-firmware-upgrade.git
cd cisco-firmware-upgrade
```

**2. Download firmware from Cisco's software page and drop both files into the project folder**

```
cisco-firmware-upgrade/
├── image_cbs_ros_3.5.4.0_release_cisco_signed.bin
└── image_cbs_ros_3.5.4.0_release_cisco_signed.bin.md5
```

The `.md5` file is on the same Cisco download page as the `.bin`. Downloading both means the launcher reads the checksum automatically — no copy-pasting required.

**3. Run the launcher**

```bash
python upgrade_tool.py
```

---

## Using the Launcher

Run `python upgrade_tool.py` and follow the prompts. No flags or arguments needed.

### Step 1 — Firmware image

The launcher searches the project folder, `~/Downloads`, and `~/Desktop` for `.bin` files and lists them automatically:

```
  ℹ  Found 1 .bin file(s):
  [1] /root/cisco-firmware-upgrade/image_cbs_ros_3.5.4.0_release_cisco_signed.bin  (38 MB)
  [2] Enter a custom path
```

After you select the file, the MD5 is loaded automatically from the matching `.md5` file:

```
  ✔  MD5 loaded from image_cbs_ros_3.5.4.0_release_cisco_signed.bin.md5: a1b2c3d4...f6a1
```

The version string is auto-guessed from the filename — just press Enter to confirm:

```
  ›  Target version [3.5.4.0]:
```

### Step 2 — Select upgrade phase

```
  [1] ALL phases (full upgrade)        ← reboots devices
  [2] Phase 1 — Pre-upgrade checks only
  [3] Phase 2 — Stage firmware only
  [4] Phase 3 — Execute upgrade only   ← reboots devices
  [5] Phase 4 — Post-upgrade verify only
  [6] Phases 1 + 2 (checks + stage, no reload)
```

> ⚠️ Options 1 and 4 will reboot target devices. Always run during a scheduled maintenance window.

### Step 3 — SSH credentials

The launcher scans `~/.ssh` and the project folder for SSH keys and lists them automatically. Pick one or enter a custom path.

```
  ℹ  Found 1 SSH key(s):
  [1] /root/.ssh/cisco_upgrade
  [2] Enter a custom path
  [3] Skip — use password auth
```

### Step 4 — Device IP addresses

Enter device IPs or hostnames one at a time. Give each a friendly alias or press Enter to accept the auto-generated one. You can remove entries by number if you make a mistake.

```
  ›  Enter IP or hostname: 10.0.1.1
  ✔  Added: device-10-0-1-1  (10.0.1.1)

  ›  Enter IP or hostname:        ← press Enter when done
```

### Step 5 — Review and confirm

A full summary is shown before anything runs:

```
  Phase    :  ALL phases (full upgrade)
  Username :  netadmin
  SSH Key  :  /root/.ssh/cisco_upgrade
  Firmware :  image_cbs_ros_3.5.4.0_release_cisco_signed.bin  (38.2 MB)
  Version  :  3.5.4.0
  MD5      :  a1b2c3d4...f6a1
  Dry run  :  no

  Target devices:
  #    Alias              IP Address
  ──────────────────────────────────────
  1.   core-sw-01         10.0.1.1
  2.   core-sw-02         10.0.1.2
```

Enter `y` to proceed or `n` to abort with no changes made.

---

## Upgrade Phases

### Phase 1 — Pre-upgrade Checks

Automatically detects platform (IOS-XE or CBS) and runs the appropriate checks:

| Check | Pass condition |
|---|---|
| Platform detection | IOS-XE or CBS identified |
| Current version | Not already on target version |
| Free flash space | > `min_flash_space` bytes (~1 GB) |
| CPU utilisation | < `cpu_threshold` % (5-minute average) |

Devices already on the target version are **skipped for all remaining phases** — no further SSH connections are made and nothing is changed on those devices.

`serial: 1` — one device checked at a time.

### Phase 2 — Stage Firmware

- Checks if the image is already on flash — skips transfer if it is (idempotent)
- Pushes the `.bin` file directly from your machine to device flash over SSH
- IOS-XE: image goes to `flash:/image.bin`, verified with `verify /md5`
- CBS: image goes to `flash://system/images/image.bin`, MD5 read from `show version`
- **Aborts immediately on MD5 mismatch**

`serial: 3` — three simultaneous transfers.

### Phase 3 — Execute Upgrade ⚠️ Reboots devices

- Sets the boot variable to the new image
- Saves configuration
- **Reloads the device** — causes a network outage on that device
- Waits up to 10 minutes for SSH to recover
- Pauses 60 seconds for services to stabilise

`serial: 1` — **one device reloaded at a time.**

### Phase 4 — Post-upgrade Verification

- Confirms running version matches target
- Captures interface and routing state
- Writes a full upgrade report to `reports/post-upgrade/`

---

## Staging Without Rebooting

If you want to copy the firmware image in advance and reboot separately during a maintenance window:

**Step 1 — Run Phases 1 and 2 now (no reboot)**

In the launcher select option `6`: *Phases 1 + 2 (checks + stage, no reload)*

This validates every device and copies the image, but stops before touching the boot variable or reloading.

**Step 2 — During your maintenance window, run Phases 3 and 4**

```
[4] Phase 3 — Execute upgrade only
[5] Phase 4 — Post-upgrade verify only
```

This way the slow file transfer is done in advance and your maintenance window only needs to cover the actual reboot time (~5–10 minutes per device).

---

## Output Files

| Path | Contents |
|---|---|
| `backups/pre-upgrade/<host>_<version>.cfg` | Full running-config backup taken before upgrade |
| `reports/pre-upgrade/<host>.yml` | Platform, version, flash space, CPU snapshot |
| `reports/post-upgrade/<host>.txt` | Version confirmed, interface state, routing summary |

---

## Safety Features

- **Nothing runs without confirmation** — full summary shown before Ansible starts
- **Already up to date = fully skipped** — devices on the target version are untouched across all four phases
- **Platform auto-detection** — correct commands used automatically for IOS-XE and CBS
- **MD5 auto-read** — checksum loaded from `.md5` file, no manual copy-paste
- **MD5 verified on device** — image integrity confirmed before boot variable is ever set
- **Pre-flight assertions** — flash space and CPU checked before any file is transferred
- **Boot variable confirmed** — `show boot` checked before reload is triggered
- **`serial: 1` on reload** — one device rebooted at a time
- **Idempotent staging** — existing flash images are reused, no unnecessary re-transfers
- **Auto directory creation** — all output folders created on first run

---

## Running Playbooks Directly

You can bypass the launcher and call `ansible-playbook` directly:

```bash
ansible-playbook site_firmware_upgrade.yml \
  -i inventory/production.yml \
  -u netadmin --private-key ~/.ssh/cisco_upgrade \
  -e "firmware_local_bin_path=/path/to/image.bin" \
  -e "firmware_target_image=image_cbs_ros_3.5.4.0_release_cisco_signed.bin" \
  -e "firmware_target_version=3.5.4.0" \
  -e "firmware_target_md5=a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
```

Run a single phase using tags:

| Tag | Phase |
|---|---|
| `preflight`, `pre_upgrade` | Phase 1 — Pre-upgrade checks |
| `stage` | Phase 2 — Image staging |
| `upgrade`, `reload` | Phase 3 — Execute upgrade |
| `verify`, `post_upgrade` | Phase 4 — Post-upgrade verification |

---

## Troubleshooting

**Device does not come back after reload**
Increase `timeout` in the `wait_for` task in `execute_upgrade.yml` (default 600 s). Some platforms take longer to boot.

**MD5 mismatch after staging**
Delete the image on the device and re-run Phase 2. Verify the `.md5` file matches what Cisco published.

**Transfer times out**
Increase `ansible_command_timeout` in `stage_firmware.yml` (default 2700 s / 45 min).

**CBS boot command not accepted**
Some CBS models do not support `boot system image-list` via CLI. If the switch comes back on the old image after reboot, set the active image manually via the web UI under *Administration > File Management > Active Image*, then reboot again.

**Boot variable not accepted (IOS-XE)**
Some platforms use `flash0:` instead of `flash:`. Adjust the `boot system` line in `execute_upgrade.yml`.

**Key file not found**
Enter the full path to the key file, or drop it in the project folder — the launcher searches there automatically alongside `~/.ssh`.

**Version not detected**
If platform detection fails, check that `show version` is returning output. The launcher expects either `IOS XE` or `Active-image` to appear in the output to identify the platform.

---

## License

MIT — see [LICENSE](LICENSE) for details.
