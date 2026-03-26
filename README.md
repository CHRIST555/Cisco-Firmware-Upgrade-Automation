# 🔧 Cisco IOS-XE Firmware Upgrade Automation

Ansible playbooks for automating end-to-end firmware upgrades on Cisco IOS-XE devices (tested on Catalyst 9000 series). Covers pre-flight validation, image staging, device reload, and post-upgrade verification — with full audit trails and configuration backups.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Usage](#usage)
- [Upgrade Phases](#upgrade-phases)
- [Output Files](#output-files)
- [Safety Features](#safety-features)
- [Troubleshooting](#troubleshooting)

---

## Overview

This project automates the full lifecycle of a Cisco firmware upgrade:

1. **Pre-flight checks** — validates version, free flash space, and CPU health; skips devices already on the target release; backs up running config
2. **Image staging** — transfers the firmware image via SCP and verifies MD5 integrity
3. **Upgrade execution** — sets the boot variable, saves config, reloads the device, and waits for it to recover
4. **Post-upgrade verification** — confirms the correct version booted, checks interface and routing protocol state, and writes a per-device report

Each phase is a standalone playbook, and a master playbook (`site_firmware_upgrade.yml`) runs all four in sequence.

---

## Project Structure

```
.
├── site_firmware_upgrade.yml      # Master playbook — runs all four phases
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
│   └── production.yml             # Host inventory with upgrade_candidates group
│
├── backups/
│   └── pre-upgrade/               # Config backups (auto-created)
│
└── reports/
    ├── pre-upgrade/               # Pre-upgrade state snapshots (auto-created)
    └── post-upgrade/              # Upgrade result reports (auto-created)
```

---

## Requirements

### Control Node

| Requirement | Version |
|---|---|
| Python | ≥ 3.9 |
| Ansible | ≥ 2.14 |
| `cisco.ios` collection | ≥ 4.6 |

Install the Cisco IOS collection:

```bash
ansible-galaxy collection install cisco.ios
```

### Network Devices

- Cisco IOS-XE devices (Catalyst 9000 series recommended)
- SSH access from the Ansible control node
- Sufficient flash space (see [Configuration](#configuration))
- SCP server reachable from the device management plane

### File Server

- SCP (or TFTP/FTP) server hosting the firmware image
- Firmware user account with read access to the image directory

---

## Quick Start

**1. Clone the repository**

```bash
clone cisco-firmware-upgrade.git
cd cisco-firmware-upgrade
```

**2. Configure your firmware variables**

Edit `group_vars/ios_routers/firmware.yml` with your target image details, file server address, and MD5 hash (from Cisco's software download page).

**3. Store the SCP password in Ansible Vault**

```bash
ansible-vault encrypt_string 'your-scp-password' --name 'vault_firmware_password'
```

Paste the output into `group_vars/ios_routers/vault.yml`.

**4. Update your inventory**

Add target devices to the `upgrade_candidates` group in your inventory file.

**5. Run the full upgrade**

```bash
ansible-playbook site_firmware_upgrade.yml \
  -i inventory/production.yml \
  --ask-vault-pass
```

---

## Configuration

All upgrade parameters are defined in `group_vars/ios_routers/firmware.yml`:

```yaml
firmware:
  target_version:       "17.09.04a"                        # Must match 'show version' output
  target_image:         "cat9k_iosxe.17.09.04a.SPA.bin"   # Exact flash filename
  target_md5:           "a1b2c3d4e5f6..."                  # MD5 from Cisco software portal
  target_size_mb:       850

  file_server:          "10.10.1.100"
  file_server_protocol: "scp"
  file_server_path:     "/firmware/cisco/ios"
  file_server_user:     "firmware"
  file_server_password: "{{ vault_firmware_password }}"    # Set via Ansible Vault

  min_flash_space:      1000000000     # Bytes — ~1 GB recommended headroom
  cpu_threshold:        80             # Max 5-min CPU % before aborting
```

> ⚠️ **Never commit plain-text passwords.** Always use `ansible-vault` for `file_server_password`.

---

## Usage

### Run all four phases

```bash
ansible-playbook site_firmware_upgrade.yml \
  -i inventory/production.yml \
  --ask-vault-pass
```

### Run a single phase (e.g. after a failed transfer)

```bash
# Stage only
ansible-playbook stage_firmware.yml -i inventory/production.yml --ask-vault-pass

# Verify only
ansible-playbook post_upgrade_verify.yml -i inventory/production.yml --ask-vault-pass
```

### Limit to specific devices

```bash
ansible-playbook site_firmware_upgrade.yml \
  -i inventory/production.yml \
  --ask-vault-pass \
  --limit "core-rtr-01,core-rtr-02"
```

### Run by phase tag (stop before reload)

```bash
# Preflight + staging only — no reloads
ansible-playbook site_firmware_upgrade.yml \
  -i inventory/production.yml \
  --ask-vault-pass \
  --tags "preflight,stage"
```

| Tag | Phase |
|---|---|
| `preflight`, `pre_upgrade` | Pre-upgrade checks |
| `stage` | Image staging |
| `upgrade`, `reload` | Execute upgrade |
| `verify`, `post_upgrade` | Post-upgrade verification |

### Dry run (no changes applied)

```bash
ansible-playbook site_firmware_upgrade.yml \
  -i inventory/production.yml \
  --ask-vault-pass \
  --check
```

> **Note:** `--check` mode skips IOS commands that send changes to the device. Use it to validate playbook logic and variable rendering, not to simulate the full upgrade flow.

---

## Upgrade Phases

### Phase 1 — Pre-upgrade Checks (`pre_upgrade_checks.yml`)

| Check | Pass Condition |
|---|---|
| Current version | Not already on target |
| Free flash space | > `min_flash_space` bytes |
| CPU utilisation | < `cpu_threshold` % (5-min avg) |

Devices already running the target version are automatically skipped. A configuration backup and state snapshot are saved to the control node before proceeding.

`serial: 1` — validated one device at a time.

### Phase 2 — Stage Firmware (`stage_firmware.yml`)

- Checks whether the image already exists on flash (idempotent — will not re-transfer)
- Copies the image via SCP with a 30-minute timeout
- Verifies MD5 hash matches `target_md5` — **aborts if there is a mismatch**

`serial: 5` — transfers run on up to five devices in parallel.

### Phase 3 — Execute Upgrade (`execute_upgrade.yml`)

- Clears existing boot statements and sets the new image
- Confirms the boot variable with `show boot`
- Saves configuration, then reloads the device
- Waits up to 10 minutes for SSH to recover (120 s initial delay)
- Pauses an additional 60 s for routing protocols to stabilise

`serial: 1` — **one device reloaded at a time**.

### Phase 4 — Post-upgrade Verification (`post_upgrade_verify.yml`)

- Asserts the running version matches `target_version`
- Captures interface status and routing protocol state (OSPF, BGP)
- Writes a full upgrade report per device to `reports/post-upgrade/`

---

## Output Files

| Path | Contents |
|---|---|
| `backups/pre-upgrade/<host>_<version>.cfg` | Full running-config backup |
| `reports/pre-upgrade/<host>.yml` | Version, flash, CPU snapshot before upgrade |
| `reports/post-upgrade/<host>.txt` | Version, interface state, OSPF/BGP status after upgrade |

---

## Safety Features

- **MD5 verification** — image integrity is confirmed before any boot variable is set
- **Pre-flight assertions** — flash space and CPU thresholds must pass or the host is skipped
- **Boot variable confirmation** — `show boot` is checked before the reload is triggered
- **`serial: 1` on reload** — only one device is rebooted at a time
- **Vault-protected secrets** — SCP password never appears in plain text
- **`no_log: true` on SCP task** — password is suppressed from Ansible output and logs
- **Idempotent staging** — existing flash images are reused; no unnecessary re-transfers

---

## Troubleshooting

**Device does not come back after reload**

Increase `timeout` in the `wait_for` task in `execute_upgrade.yml` (default: 600 s). Chassis-based platforms with many line cards may take longer to boot.

**MD5 mismatch after staging**

Delete the corrupt image on the device (`del flash:<image>`), verify the `target_md5` value in `firmware.yml` matches Cisco's published checksum, and re-run `stage_firmware.yml`.

**SCP transfer times out**

Increase `ansible_command_timeout` on the copy task (default: 1800 s / 30 min). Also check firewall rules between the device management interface and the file server.

**Boot variable not accepted**

Some IOS-XE versions require the full path (e.g. `flash0:` instead of `flash:`). Adjust the `boot system` line in `execute_upgrade.yml` to match your platform.

**Wrong prompt order on reload**

The prompt order for `reload` (`Save?` vs `Proceed with reload?`) varies by IOS-XE version. If the reload task hangs, swap the order of `prompt`/`answer` entries in `execute_upgrade.yml`.

---

## License

MIT — see [LICENSE](LICENSE) for details.
