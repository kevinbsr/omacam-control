<div align="center">

# 📷 Omacam Control

**Native, lightweight V4L2 webcam sensor calibration, exposure controls, and hardware privacy killswitch for Omarchy Quattro.**

[![Omarchy Plugin](https://img.shields.io/badge/Omarchy-Plugin-blue?style=for-the-badge&logo=archlinux)](https://plugins.omarchy.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Arch%20Linux%20%7C%20Hyprland-lightgrey?style=for-the-badge)](https://github.com/kevinbsr/omacam-control)

<br />

<img src="preview.png" alt="Omacam Control UI Preview" width="480" />

</div>

---

## 🎯 Overview

Most Linux webcam utilities either rely on heavy GUI suites or load multimedia frameworks (`QtMultimedia`, GStreamer) into the desktop shell. On hybrid graphics laptops (e.g. AMD iGPU + NVIDIA dGPU), opening media pipelines keeps the dedicated GPU awake, burning ~10W of battery at idle.

**Omacam Control** is designed from scratch to be **100% battery-safe, ultra-lightweight, and native**:
- Directly adjusts V4L2 hardware sensor registers without touching the dGPU.
- **Appears on-demand** in the bar only when an application (Google Meet, Discord, Teams, Zoom, OBS, Snapshot) starts capturing video.
- Provides studio-grade lighting and exposure calibration in real time.
- Features a **one-click hardware privacy shutter**.

---

## ✨ Features

- 🟢 **On-Demand Auto-Show & Auto-Hide:** Automatically appears on the bar when camera capture starts and cleanly disappears when idle.
- 🔋 **Zero dGPU Power Drain:** Built without `QtMultimedia`. Hybrid laptops safely maintain `D3cold` sleep state.
- ⚡ **Physical Privacy Killswitch:** Right-click the bar icon to instantly cut power to the USB webcam at the kernel level (`authorized = 0`), powering down sensor and LED across all active calls. Only the USB device that owns the detected V4L2 capture node is touched, and only if its interface is USB video class (see [Privacy shutter setup](#-privacy-shutter-setup)).
- 🎛️ **Live Hardware Sensor Controls:**
  - **Exposure Time & Lock Manual Mode:** Eliminate camera blowout, flickering, and motion blur.
  - **Dynamic Framerate:** Toggle low-light adaptive framerate.
  - **Image Adjustments:** Sliders for Brightness, Contrast, Gamma (shadow detail recovery), Digital Gain, and Backlight Compensation.
- 🌟 **One-Click Quick Presets (2x2 Grid):**
  - `󰓎 Balanced`: Studio-calibrated natural lighting, shadow recovery, and stable 30fps lock.
  - `󰖔 Low Light`: High digital gain, increased gamma, and extended sensor exposure.
  - `󰖙 Bright Room`: Lowered exposure and reduced gain to prevent washed-out backgrounds.
  - `󰑐 Auto`: Restores hardware auto-exposure and default sensor defaults.

---

## 🖱️ Bar Controls & Shortcuts

| Action | Result |
| :--- | :--- |
| **Left-Click** on `󰄀` | Opens / closes the Omacam Control calibration panel. |
| **Right-Click** on `󰄀` | Toggles **Privacy Shutter** (turns icon to `󰗟` and cuts hardware video feed). |
| **Wheel Scroll on Sliders** | Passes through smoothly to scroll the panel without accidentally altering values. |

---

## 📦 Requirements

- **Omarchy Quattro** (`omarchy-shell` / `quickshell`)
- **Python 3** (standard library only). Controls are read and written with V4L2 ioctls, so `v4l-utils` is not needed.
- **`fuser`** (`psmisc`, optional): only used to detect capture on cameras whose streaming state sysfs cannot report (non-USB or bulk-transfer UVC).

### 🔒 Privacy shutter setup

The shutter writes `/sys/bus/usb/devices/<port>/authorized`, which only root can write by default. The plugin never escalates privileges itself. If you want the shutter, grant write access to your camera's attribute once, as root, scoped to its USB vendor and product IDs (find them with `lsusb`). Desktop sessions reach `/dev/video*` through logind ACLs rather than the `video` group, so use a dedicated group:

```bash
groupadd --system omacam
usermod -aG omacam "$USER"   # log out and back in afterwards
```

Then create `/etc/udev/rules.d/99-omacam-privacy.rules`, replacing the IDs with your camera's:

```
ACTION=="add|change", SUBSYSTEM=="usb", ATTR{idVendor}=="0c45", ATTR{idProduct}=="6720", TEST=="authorized", RUN+="/bin/sh -c 'chgrp omacam /sys%p/authorized && chmod 0664 /sys%p/authorized'"
```

Reload with `udevadm control --reload && udevadm trigger --action=change --subsystem-match=usb`. Without this setup everything else works and the shutter reports a permission error.

While a camera is blocked, the helper records its USB sysfs path and IDs in `~/.local/state/omacam-control/privacy.json`, and unblocking re-authorizes only that device after checking the IDs still match.

---

## 🚀 Installation

### Via Omarchy CLI:

```bash
omarchy plugin add https://github.com/kevinbsr/omacam-control
```

### Manual Installation:

1. Clone this repository into your Omarchy plugins directory:
   ```bash
   git clone https://github.com/kevinbsr/omacam-control.git ~/.config/omarchy/plugins/kevin.camera
   ```

2. Add the widget to your `~/.config/omarchy/shell.json` inside `bar.layout.right`:
   ```json
   {
     "id": "kevin.camera"
   }
   ```

3. Restart the shell:
   ```bash
   omarchy restart shell
   ```

---

## 💻 CLI & IPC Control

You can trigger Omacam Control actions directly from scripts, keybindings, or Hyprland config:

```bash
# Toggle the settings panel
omarchy-shell shell toggle kevin.camera

# List detected capture devices
python3 ~/.config/omarchy/plugins/kevin.camera/camera_ctl.py devices

# Apply presets (balanced, night, bright, auto); the device is optional and
# defaults to the first detected capture device
python3 ~/.config/omarchy/plugins/kevin.camera/camera_ctl.py preset /dev/video2 balanced

# Toggle hardware privacy killswitch
python3 ~/.config/omarchy/plugins/kevin.camera/camera_ctl.py privacy /dev/video2 1 # Block
python3 ~/.config/omarchy/plugins/kevin.camera/camera_ctl.py privacy 0            # Unblock
```

Device arguments must resolve to a V4L2 video capture node (`/dev/videoN` or a `/dev/v4l/by-id` link); anything else is rejected with exit code 2.

---

## 📜 License

Distributed under the [MIT License](LICENSE). Copyright © 2026 Kevin.
