# 🔧 Cisco Firmware Upgrade Automation

Ansible playbooks for automating end-to-end firmware upgrades on Cisco switches, driven by an interactive Python CLI launcher.

**Supported platforms:** Cisco IOS-XE (Catalyst) and Cisco CBS (Business Switch)

No file server. No config file editing. No vault setup. Drop your firmware files in the project folder and run the launcher — it handles everything else, including starting a temporary TFTP server for CBS switches.

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

1. **Pre-flight checks** — detects platform, validates version, checks free flash space and CPU health, backs up running config. Devices already on the target version are skipped entirely.
2. **Image staging** — transfers the firmware image to each device. IOS-XE receives a direct SCP push. CBS switches pull the file from a temporary TFTP server started automatically on your machine.
3. **Upgrade execution** — saves config, optionally reloads the device, and waits for it to recover.
4. **Post-upgrade verification** — confirms the correct version booted, checks interface and routing state, writes a per-device report.

---

## How It Works

**Platform auto-detection** — each playbook reads `show version` and automatically determines whether the device is IOS-XE or CBS. The correct commands run for each platform without any manual configuration.

**Already up to date = fully skipped** — if a device is already running the target version, all four phases skip it completely. No further connections are made and nothing is changed.

**IOS-XE file transfer** — the firmware `.bin` is pushed directly from your machine to device flash over the existing SSH connection using SCP. No file server needed.

**CBS file transfer** — CBS switches do not accept SCP file pushes. Instead, the launcher automatically starts a temporary TFTP server on your machine before Ansible runs. The CBS switch pulls the firmware using `boot system tftp://`. The TFTP server shuts down and cleans up automatically after the run.

**Reload is optional** — when Phase 3 is included, the launcher asks whether to send the reload command. You can stage the firmware now and reload separately during a scheduled maintenance window.

---

## Project Structure

```
cisco-firmware-upgrade/
├── upgrade_tool.py                     # Interactive CLI launcher — start here
│
├── image_cbs_ros_3.5.3.3_...bin       # ← drop your firmware .bin file here
├── image_cbs_ros_3.5.3.3_...bin.md5   # ← drop your .md5 checksum file here
│
├── site_firmware_upgrade.yml           # Master playbook — runs all four phases
├── pre_upgrade_checks.yml              # Phase 1: platform detect, validation, backup
├── stage_firmware.yml                  # Phase 2: file transfer & verification
├── execute_upgrade.yml                 # Phase 3: save config, optional reload, wait
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
│   └── pre-upgrade/                    # Config backups (auto-created)
│
├── reports/
│   ├── pre-upgrade/                    # Pre-upgrade snapshots (auto-created)
│   ├── post-upgrade/                   # Upgrade result reports (auto-created)
│   └── status/                         # Per-device status files for summary table
│
└── requirements.txt                    # Python dependencies
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
| `tftpy` (Python) | any |

```bash
pip install -r requirements.txt
ansible-galaxy collection install cisco.ios ansible.netcommon
```

### Network Devices

- Cisco IOS-XE (Catalyst 9000 series) or Cisco CBS (CBS250 / CBS350 series)
- SSH access from your machine to device management interfaces
- For CBS: UDP port 69 (TFTP) must be reachable from the switch to your machine
- Enough free flash space for the firmware image

### Firewall (CBS only)

The CBS switch pulls firmware via TFTP (UDP port 69). Open this port before running:

```bash
sudo ufw allow 69/udp
sudo ufw allow 69/tcp
```

You can close it again after the upgrade:

```bash
sudo ufw delete allow 69/udp
sudo ufw delete allow 69/tcp
```

> **Note:** Port 69 is a privileged port. Run `upgrade_tool.py` with `sudo` or ensure your user has permission to bind to it.

---

## Quick Start

**1. Clone the repository**

```bash
git clone https://github.com/your-org/cisco-firmware-upgrade.git
cd cisco-firmware-upgrade
```

**2. Install Python dependencies**

```bash
pip install -r requirements.txt
ansible-galaxy collection install cisco.ios ansible.netcommon
```

**3. Download firmware from Cisco's software page and drop both files into the project folder**

```
cisco-firmware-upgrade/
├── image_cbs_ros_3.5.3.3_release_cisco_signed.bin
└── image_cbs_ros_3.5.3.3_release_cisco_signed.bin.md5
```

The `.md5` file is on the same Cisco download page as the `.bin`. The launcher reads the checksum automatically — no copy-pasting required.

**4. Run the launcher**

```bash
sudo python upgrade_tool.py
```

> `sudo` is required on Linux/Mac so the TFTP server can bind to port 69. If you are only upgrading IOS-XE devices, `sudo` is not needed.

---

## Using the Launcher

Run `sudo python upgrade_tool.py` and follow the prompts.

### Step 1 — Firmware image

The launcher searches the project folder, `~/Downloads`, and `~/Desktop` for `.bin` files:

```
  ℹ  Found 1 .bin file(s):
  [1] /root/cisco-firmware-upgrade/image_cbs_ros_3.5.3.3_release_cisco_signed.bin  (41 MB)
  [2] Enter a custom path
```

The MD5 is loaded automatically from the matching `.md5` file:

```
  ✔  MD5 loaded from image_cbs_ros_3.5.3.3_release_cisco_signed.bin.md5: 96af8f2d...f4be
```

The version string is auto-guessed from the filename — press Enter to confirm or type a correction:

```
  ›  Target version [3.5.3.3]:
```

### Step 2 — Select upgrade phase

```
  [1] ALL phases (full upgrade)               ← may reboot devices
  [2] Phase 1 — Pre-upgrade checks only
  [3] Phase 2 — Stage firmware only
  [4] Phase 3 — Execute upgrade only          ← may reboot devices
  [5] Phase 4 — Post-upgrade verify only
  [6] Phases 1 + 2 (checks + stage, no reload)
```

### Step 3 — SSH credentials

The launcher scans `~/.ssh` and the project folder for SSH keys automatically. Pick one or enter a custom path.

### Step 4 — Device IP addresses

Enter device IPs or hostnames one at a time. Give each a friendly alias or press Enter for the auto-generated one.

```
  ›  Enter IP or hostname: 192.168.1.10
  ✔  Added: device-192-168-1-10  (192.168.1.10)

  ›  Enter IP or hostname:        ← press Enter when done
```

### Step 5 — Run options

```
  ›  Dry run? (--check, no changes applied) (y/n) [n]:
  ›  Verbose output? (-v) (y/n) [n]:

  ℹ  Phase 3 will reload devices to apply the new firmware.
  ⚠  Only proceed with reload during a scheduled maintenance window.
  ›  Send reload command to devices? (y/n) [y]:
```

The reload prompt only appears when Phase 3 is included. Choosing `n` stages the firmware and saves config but skips the reboot — devices continue running normally until you trigger Phase 3 separately.

### Step 6 — TFTP server (CBS devices)

For CBS devices, the launcher starts a temporary TFTP server automatically:

```
  ┌─ TFTP Server ─────────────────────────────────────────────
  ✔  TFTP server started on 192.168.26.110:69
  ℹ  Serving: image_cbs_ros_3.5.3.3_release_cisco_signed.bin
  ℹ  CBS switches will pull the firmware from this server.
```

The server runs during the Ansible execution and shuts down automatically when finished.

### Step 7 — Review and confirm

```
  Phase    :  ALL phases (full upgrade)
  Username :  netadmin
  SSH Key  :  /root/.ssh/cisco_upgrade
  Firmware :  image_cbs_ros_3.5.3.3_release_cisco_signed.bin  (41.3 MB)
  Version  :  3.5.3.3
  MD5      :  96af8f2d...f4be
  Dry run  :  no
  Reload   :  YES — devices will reboot

  Target devices:
  #    Alias              IP Address
  ──────────────────────────────────────
  1.   core-sw-01         192.168.1.10
  2.   core-sw-02         192.168.1.11
```

### Step 8 — Upgrade summary

After the run, a summary table shows the outcome for every device:

```
  Device         IP               Platform   Status
  ──────────────────────────────────────────────────────────────
  core-sw-01     192.168.1.10     CBS        ✔ Upgrade complete (3.5.3.3)
  core-sw-02     192.168.1.11     CBS        ✔ Already up to date (3.5.3.3)

  ✔  All devices processed successfully.
```

Possible status values:

| Status | Meaning |
|---|---|
| `Already up to date` | Device was skipped — already on target version |
| `Pre-checks passed` | Phase 1 completed — ready to stage |
| `Image staged — reboot required` | Phase 2 done — firmware ready, reboot pending |
| `Upgrade complete` | Phase 4 confirmed new version is running |
| `FAILED` | Something went wrong — check `reports/post-upgrade/` |

---

## Upgrade Phases

### Phase 1 — Pre-upgrade Checks

| Check | Pass condition |
|---|---|
| Platform detection | IOS-XE or CBS identified |
| Current version | Not already on target version |
| Free flash space | > `min_flash_space` bytes (IOS-XE only) |
| CPU utilisation | < `cpu_threshold` % (IOS-XE only) |

Devices already on the target version are skipped for all remaining phases.

`serial: 1` — one device at a time.

### Phase 2 — Stage Firmware

**IOS-XE:**
- Checks if image already exists on flash (skips transfer if it does)
- Pushes `.bin` directly from your machine via SCP
- Verifies MD5 with `verify /md5 flash:`

**CBS:**
- The launcher starts a temporary TFTP server on your machine
- Runs `boot system tftp://your-ip/image.bin` on the switch
- The switch downloads the image and marks it as active on next boot
- Transfer takes approximately 2 minutes per switch

`serial: 3` — three simultaneous transfers.

### Phase 3 — Execute Upgrade ⚠️ May reboot devices

- Saves configuration with `write memory`
- If reload was approved: sends `reload`, waits up to 10 minutes for SSH to recover, pauses 60 s for services to stabilise
- If reload was skipped: saves config and stops — devices remain online

`serial: 1` — **one device at a time.**

### Phase 4 — Post-upgrade Verification

- Confirms running version matches target
- Captures interface status and routing state
- Writes a full upgrade report to `reports/post-upgrade/`

---

## Staging Without Rebooting

To copy the firmware in advance and reboot separately during a maintenance window:

**Option A — Use the reload prompt**

Run the full upgrade (option 1) and select `n` when asked about the reload. The firmware is staged and config is saved, but no reboot occurs.

**Option B — Use phase tags**

```
[6] Phases 1 + 2 (checks + stage, no reload)
```

Then during your maintenance window run:

```
[4] Phase 3 — Execute upgrade only
[5] Phase 4 — Post-upgrade verify only
```

---

## Output Files

| Path | Contents |
|---|---|
| `backups/pre-upgrade/<host>_<version>.cfg` | Full running-config backup |
| `reports/pre-upgrade/<host>.yml` | Platform, version, flash space, CPU snapshot |
| `reports/post-upgrade/<host>.txt` | Version confirmed, interface state, routing summary |
| `reports/status/<host>.status` | Machine-readable status used by the summary table |

---

## Safety Features

- **Nothing runs without confirmation** — full summary shown before Ansible starts
- **Reload is optional** — choose whether to reboot during the run or later
- **Already up to date = fully skipped** — devices on the target version are untouched
- **Platform auto-detection** — correct commands used automatically for IOS-XE and CBS
- **MD5 auto-read** — checksum loaded from `.md5` file, no manual copy-paste
- **MD5 verified on device** — IOS-XE verifies image integrity before boot variable is set
- **Pre-flight assertions** — flash space and CPU checked before any file is transferred
- **`serial: 1` on reload** — one device rebooted at a time
- **Idempotent staging** — IOS-XE skips transfer if image already on flash
- **TFTP server auto-cleanup** — temp files and server always cleaned up after run
- **Auto directory creation** — all output folders created on first run

---

## Running Playbooks Directly

You can bypass the launcher and call `ansible-playbook` directly:

```bash
ansible-playbook site_firmware_upgrade.yml \
  -i inventory/production.yml \
  -u netadmin --private-key ~/.ssh/cisco_upgrade \
  -e "firmware_local_bin_path=/path/to/image.bin" \
  -e "firmware_target_image=image_cbs_ros_3.5.3.3_release_cisco_signed.bin" \
  -e "firmware_target_version=3.5.3.3" \
  -e "firmware_target_md5=96af8f2d8f34821f091ca1b26a17f4be" \
  -e "cbs_send_reload=true"
```

Set `cbs_send_reload=false` to skip the reload.

| Tag | Phase |
|---|---|
| `preflight`, `pre_upgrade` | Phase 1 — Pre-upgrade checks |
| `stage` | Phase 2 — Image staging |
| `upgrade`, `reload` | Phase 3 — Execute upgrade |
| `verify`, `post_upgrade` | Phase 4 — Post-upgrade verification |

---

## Troubleshooting

**Device does not come back after reload**
Increase `timeout` in the `wait_for` task in `execute_upgrade.yml` (default 600 s).

**CBS transfer fails or times out**
Ensure UDP port 69 is open on your machine (`sudo ufw allow 69/udp`) and that the switch can reach your machine's IP. Run with `sudo` so the TFTP server can bind to port 69.

**CBS transfer completes but switch boots old firmware**
The `boot system tftp://` command stages the image for the next boot. The switch must be reloaded to apply it — run Phase 3 if you skipped it.

**IOS-XE MD5 mismatch after staging**
Delete the image on the device (`del flash:<image>`), verify the `.md5` file matches Cisco's published value, and re-run Phase 2.

**Transfer times out on IOS-XE**
Increase `ansible_command_timeout` in `stage_firmware.yml` (default 2700 s / 45 min).

**Boot variable not accepted (IOS-XE)**
Some platforms use `flash0:` instead of `flash:`. Adjust the `boot system` line in `execute_upgrade.yml`.

**Key file not found**
Enter the full path to the key file, or drop it in the project folder — the launcher searches there automatically alongside `~/.ssh`.

**Version not detected**
Ensure the device responds to `show version` and that the output contains either `IOS XE` (Catalyst) or `Active-image` (CBS).

---

## License

MIT — see [LICENSE](LICENSE) for details.
