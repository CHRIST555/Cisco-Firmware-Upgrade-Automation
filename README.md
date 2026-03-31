# 🔧 Cisco IOS-XE Firmware Upgrade Automation

Ansible playbooks for automating end-to-end firmware upgrades on Cisco IOS-XE devices (tested on Catalyst 9000 series), driven by an interactive Python CLI launcher. Enter your device IPs, pick your SSH key, select a firmware image, choose an upgrade phase — and let it run.

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
2. **Image staging** — transfers the firmware image via SCP and verifies MD5 integrity
3. **Upgrade execution** — sets the boot variable, saves config, reloads the device, and waits for it to recover
4. **Post-upgrade verification** — confirms the correct version booted, checks interface and routing protocol state, and writes a per-device report

Everything is driven through `upgrade_tool.py` — an interactive terminal launcher that walks you through device IPs, credentials, firmware selection, and phase choice before building and running the Ansible command.

---

## Project Structure

```
.
├── upgrade_tool.py                # Interactive CLI launcher — start here
├── site_firmware_upgrade.yml      # Master playbook — imports all four phases
├── pre_upgrade_checks.yml         # Phase 1: readiness validation & backup
├── stage_firmware.yml             # Phase 2: SCP transfer & MD5 verification
├── execute_upgrade.yml            # Phase 3: boot variable, reload, wait
├── post_upgrade_verify.yml        # Phase 4: version check & service health
│
├── group_vars/
│   └── ios_routers/
│       ├── firmware.yml           # Upgrade variables (image, server, thresholds)
│       └── vault.yml              # Ansible Vault — encrypted secrets
│
├── inventory/
│   └── production.yml             # Optional static host inventory
│
├── backups/
│   └── pre-upgrade/               # Config backups (auto-created per run)
│
└── reports/
    ├── pre-upgrade/               # Pre-upgrade state snapshots
    └── post-upgrade/              # Per-device upgrade result reports
```

---

## Requirements

### Control Node

| Requirement | Version |
|---|---|
| Python | ≥ 3.9 |
| Ansible | ≥ 2.14 |
| `cisco.ios` collection | ≥ 4.6 |

Install dependencies:

```bash
pip install ansible
ansible-galaxy collection install cisco.ios
```

> `paramiko` is optional but recommended for SSH key handling: `pip install paramiko`

### Network Devices

- Cisco IOS-XE devices (Catalyst 9000 series recommended)
- SSH access from the Ansible control node
- SCP server reachable from the device management plane

### File Server

- SCP (or TFTP/FTP) server hosting the firmware `.bin` image
- A user account with read access to the image directory

---

## Quick Start

**1. Clone the repository**

```bash
git clone https://github.com/your-org/cisco-firmware-upgrade.git
cd cisco-firmware-upgrade
```

**2. Set the firmware details**

Edit `group_vars/ios_routers/firmware.yml` with your target image name, MD5 hash (from Cisco's software download page), and file server address.


# SSH server is usually already installed, but just in case
sudo apt install openssh-server

# Create a locked-down firmware user
sudo useradd -m -s /bin/bash firmware
sudo passwd firmware          # set the password — this goes into vault.yml

# Create the firmware directory
sudo mkdir -p /firmware/cisco/ios
sudo chown firmware:firmware /firmware/cisco/ios

# Copy your .bin file onto the server
scp cat9k_iosxe.17.09.04a.SPA.bin firmware@<server-ip>:/firmware/cisco/ios/
```

Then confirm the router can actually reach it before running the playbook:
```
router# ping 10.10.1.100 source <management-interface>
router# copy scp://firmware@10.10.1.100/firmware/cisco/ios/cat9k_iosxe.17.09.04a.SPA.bin flash:

**3. Store the SCP password in Ansible Vault**

```bash
ansible-vault encrypt_string 'your-scp-password' --name 'vault_firmware_password'
```

Paste the output into `group_vars/ios_routers/vault.yml`.

**4. Run the launcher**

```bash
python upgrade_tool.py
```

The tool will guide you through the rest interactively.

---

## Using the Launcher

`upgrade_tool.py` is a step-by-step terminal wizard. No flags or arguments needed — just run it and follow the prompts.

### Step 1 — Select upgrade phase

```
  ┌─ Select Upgrade Phase ────────────────────────────────────
  [1] ALL phases (full upgrade)
  [2] Phase 1 — Pre-upgrade checks only
  [3] Phase 2 — Stage firmware only
  [4] Phase 3 — Execute upgrade only
  [5] Phase 4 — Post-upgrade verify only
  [6] Phases 1 + 2 (check + stage, no reload)
```

### Step 2 — SSH credentials

- Enter your SSH username (defaults to your current system user)
- The tool scans `~/.ssh` and lists any existing keys — pick one, enter a custom path, or skip to use password auth
- Optionally enter your Ansible Vault password (hidden input) to decrypt the SCP credentials in `vault.yml`

### Step 3 — Firmware image

The tool searches `./firmware`, `~/Downloads`, `/tmp`, and the current directory for `.bin` files and lists them with their sizes. Pick one from the list or enter a custom path.

### Step 4 — Target devices

Choose how to specify your devices:

**Option 1 — Enter IP addresses now (recommended)**

Type device IPs or hostnames one at a time. The tool:
- Validates each entry as a proper IPv4/IPv6 address or hostname
- Resolves hostnames to IPs automatically (DNS lookup)
- Rejects duplicates
- Lets you assign a friendly alias to each device (e.g. `core-rtr-01`)
- Lets you remove entries by number if you make a mistake
- Writes a temporary Ansible inventory file automatically — deleted after the run

```
  ›  Enter IP address or hostname: 10.0.1.1
  ✔  Added: device-10-0-1-1  (10.0.1.1)

  ›  Enter IP address or hostname: core-rtr-02.example.com
  ✔  Resolved core-rtr-02.example.com → 10.0.1.2
  ✔  Added: core-rtr-02.example.com  (10.0.1.2)

  ›  Enter IP address or hostname:   ← press Enter when done
```

**Option 2 — Use an existing inventory file**

Point to your own `inventory/production.yml` or any other Ansible inventory file. Optionally limit to specific hostnames.

### Step 5 — Run options

Choose whether to do a dry run (`--check`, no changes applied) and whether to enable verbose Ansible output.

### Step 6 — Summary & confirm

Before anything runs, the tool shows a full summary including a table of every target device:

```
  Phase      :  ALL phases (full upgrade)
  Username   :  netadmin
  SSH Key    :  /home/user/.ssh/id_ed25519
  Vault      :  ✔ configured
  Firmware   :  cat9k_iosxe.17.09.04a.SPA.bin
  Dry run    :  no

  Target devices:
  #    Alias                     IP Address
  ────────────────────────────────────────────────
  1.   core-rtr-01               10.0.1.1
  2.   core-rtr-02               10.0.1.2
  3.   dist-sw-01                10.0.2.1
```

Enter `y` to proceed or `n` to abort with no changes made.

---

## Configuration

All upgrade parameters live in `group_vars/ios_routers/firmware.yml`:

```yaml
firmware:
  target_version:       "17.09.04a"                        # Must match 'show version' output exactly
  target_image:         "cat9k_iosxe.17.09.04a.SPA.bin"   # Exact filename on flash / file server
  target_md5:           "a1b2c3d4e5f6..."                  # MD5 from Cisco software download portal
  target_size_mb:       850                                # For informational logging only

  file_server:          "10.10.1.100"
  file_server_protocol: "scp"
  file_server_path:     "/firmware/cisco/ios"
  file_server_user:     "firmware"
  file_server_password: "{{ vault_firmware_password }}"    # Set via Ansible Vault — never plain text

  min_flash_space:      1000000000     # Bytes of free flash required (~1 GB)
  cpu_threshold:        80             # Max 5-minute CPU % allowed before aborting
```

> ⚠️ **Never commit plain-text passwords.** Always use `ansible-vault` for `file_server_password`.

---

## Running Playbooks Directly

You can bypass the launcher and call `ansible-playbook` directly if needed.

### Full upgrade

```bash
ansible-playbook site_firmware_upgrade.yml \
  -i inventory/production.yml \
  -u netadmin --private-key ~/.ssh/id_ed25519 \
  --ask-vault-pass
```

### Single phase via tag

```bash
# Stage firmware only
ansible-playbook site_firmware_upgrade.yml \
  -i inventory/production.yml \
  --tags stage --ask-vault-pass

# Post-upgrade verification only
ansible-playbook site_firmware_upgrade.yml \
  -i inventory/production.yml \
  --tags verify --ask-vault-pass
```

### Limit to specific devices

```bash
ansible-playbook site_firmware_upgrade.yml \
  -i inventory/production.yml \
  --limit "core-rtr-01,core-rtr-02" \
  --ask-vault-pass
```

### Dry run

```bash
ansible-playbook site_firmware_upgrade.yml \
  -i inventory/production.yml \
  --check --ask-vault-pass
```

| Tag | Phase |
|---|---|
| `preflight`, `pre_upgrade` | Phase 1 — Pre-upgrade checks |
| `stage` | Phase 2 — Image staging |
| `upgrade`, `reload` | Phase 3 — Execute upgrade |
| `verify`, `post_upgrade` | Phase 4 — Post-upgrade verification |

---

## Upgrade Phases

### Phase 1 — Pre-upgrade Checks (`pre_upgrade_checks.yml`)

| Check | Pass condition |
|---|---|
| Current version | Not already running target version |
| Free flash space | > `min_flash_space` bytes (~1 GB) |
| CPU utilisation | < `cpu_threshold` % (5-minute average) |

Devices already on the target version are skipped automatically. A full config backup and state snapshot are saved before any changes are made.

`serial: 1` — one device checked at a time.

### Phase 2 — Stage Firmware (`stage_firmware.yml`)

- Checks whether the image already exists on flash — skips transfer if it does (idempotent)
- Copies the image via SCP with a 30-minute timeout
- Verifies MD5 hash — **aborts immediately if there is a mismatch**
- SCP password is suppressed from all logs (`no_log: true`)

`serial: 5` — up to five simultaneous transfers.

### Phase 3 — Execute Upgrade (`execute_upgrade.yml`)

- Clears existing boot statements and sets the new image
- Confirms boot variable with `show boot` before reloading
- Saves configuration, then issues `reload`
- Waits up to 10 minutes for SSH to recover (120 s initial delay)
- Pauses 60 s for routing protocols to stabilise after reboot

`serial: 1` — **one device reloaded at a time.**

### Phase 4 — Post-upgrade Verification (`post_upgrade_verify.yml`)

- Asserts running version matches `target_version` — fails loudly if not
- Captures interface status (`show ip interface brief`)
- Checks OSPF neighbour and BGP summary state
- Writes a full upgrade report per device to `reports/post-upgrade/`

---

## Output Files

| Path | Contents |
|---|---|
| `backups/pre-upgrade/<host>_<version>.cfg` | Full running-config backup |
| `reports/pre-upgrade/<host>.yml` | Version, flash space, CPU snapshot before upgrade |
| `reports/post-upgrade/<host>.txt` | Version confirmed, interface state, OSPF/BGP status |

---

## Safety Features

- **Interactive review** — full device list and command shown before anything runs
- **MD5 verification** — image integrity confirmed before boot variable is ever set
- **Pre-flight assertions** — flash space and CPU thresholds must pass or the host is skipped
- **Boot variable confirmation** — `show boot` checked before reload is triggered
- **`serial: 1` on reload** — only one device rebooted at a time
- **Vault-protected secrets** — SCP password never stored in plain text
- **`no_log: true` on SCP task** — password suppressed from Ansible output and logs
- **Temp file cleanup** — dynamically generated inventory and vault password files are always deleted after the run, even on abort or error
- **Idempotent staging** — existing flash images are reused; no unnecessary re-transfers

---

## Troubleshooting

**Device does not come back after reload**
Increase the `timeout` value in the `wait_for` task in `execute_upgrade.yml` (default: 600 s). Chassis platforms with many line cards may take longer to fully boot.

**MD5 mismatch after staging**
Delete the image on the device with `del flash:<image>`, verify `target_md5` in `firmware.yml` against Cisco's published checksum, and re-run the staging phase.

**SCP transfer times out**
Increase `ansible_command_timeout` on the copy task (default: 1800 s). Check firewall rules between the device management interface and the file server on port 22.

**Boot variable not accepted**
Some IOS-XE platforms use `flash0:` instead of `flash:`. Adjust the `boot system` line in `execute_upgrade.yml` to match your platform.

**Wrong prompt order on reload**
The prompt order (`Save?` vs `Proceed with reload?`) varies by IOS-XE version. If the reload task hangs, swap the `prompt`/`answer` entries in `execute_upgrade.yml`.

**Hostname not resolving in the launcher**
If DNS is not available from the control node, enter IP addresses directly instead of hostnames. The generated inventory uses the resolved IP, so DNS is only needed at launch time.

---

## License

MIT — see [LICENSE](LICENSE) for details.
