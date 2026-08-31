#!/usr/bin/env python3
import sys
import subprocess
import json
import re
import os
import time

PRESETS = {
    "balanced": {
        "auto_exposure": 1,
        "exposure_time_absolute": 320,
        "gamma": 110,
        "backlight_compensation": 1,
        "brightness": 0,
        "contrast": 15,
        "saturation": 80,
        "white_balance_automatic": 1,
        "gain": 1,
        "exposure_dynamic_framerate": 0
    },
    "night": {
        "auto_exposure": 1,
        "exposure_time_absolute": 450,
        "gamma": 120,
        "backlight_compensation": 1,
        "brightness": 5,
        "contrast": 15,
        "saturation": 80,
        "white_balance_automatic": 1,
        "gain": 2,
        "exposure_dynamic_framerate": 0
    },
    "bright": {
        "auto_exposure": 1,
        "exposure_time_absolute": 200,
        "gamma": 100,
        "backlight_compensation": 0,
        "brightness": -5,
        "contrast": 15,
        "saturation": 80,
        "white_balance_automatic": 1,
        "gain": 1,
        "exposure_dynamic_framerate": 0
    },
    "auto": {
        "auto_exposure": 3,
        "backlight_compensation": 1,
        "brightness": 0,
        "contrast": 0,
        "saturation": 80,
        "white_balance_automatic": 1,
        "gamma": 100,
        "gain": 1,
        "exposure_dynamic_framerate": 0
    }
}

def is_camera_in_use():
    # 1. Check all physical video device nodes (/dev/video*)
    try:
        for f in sorted(os.listdir("/dev")):
            if f.startswith("video"):
                num = f.replace("video", "")
                if num in ("0", "1", "20"):  # Loopbacks (OBS, DroidCam, Camera Effects)
                    continue
                path = os.path.join("/dev", f)
                res = subprocess.run(["fuser", path], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                if res.returncode == 0 and res.stdout.strip():
                    pids = res.stdout.decode().split()
                    for pid in pids:
                        clean_pid = pid.strip().rstrip("m").rstrip("e")
                        if clean_pid and clean_pid != str(os.getpid()):
                            return True
    except Exception:
        pass

    # 2. Check PipeWire Video/Source streaming state & active links
    try:
        nodes = json.loads(subprocess.check_output(["pw-dump"], text=True, stderr=subprocess.DEVNULL))
        for n in nodes:
            props = n.get("info", {}).get("props", {})
            if props.get("media.class") == "Video/Source":
                state = n.get("info", {}).get("state")
                if state in ("streaming", "active"):
                    return True
            if n.get("type") == "PipeWire:Interface:Link":
                if n.get("info", {}).get("state") in ("active", "streaming"):
                    if "video" in str(props).lower():
                        return True
    except Exception:
        pass

    return False

def get_devices():
    devices = []
    try:
        out = subprocess.check_output(["v4l2-ctl", "--list-devices"], text=True, stderr=subprocess.DEVNULL)
        blocks = out.strip().split("\n\n")
        for b in blocks:
            lines = b.strip().split("\n")
            if not lines:
                continue
            name = lines[0].strip().rstrip(":")
            devs = [l.strip() for l in lines[1:] if l.strip().startswith("/dev/video")]
            for dev in devs:
                res = subprocess.run(["v4l2-ctl", "-d", dev, "--list-ctrls"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                if res.stdout and ("brightness" in res.stdout or "exposure" in res.stdout or "User Controls" in res.stdout):
                    devices.append({"name": name, "device": dev})
                    break
    except Exception:
        pass
    devices.sort(key=lambda d: 0 if "Integrated" in d["name"] or "usb" in d["name"] else 1)
    if not devices and os.path.exists("/dev/video7"):
        devices.append({"name": "Integrated Webcam", "device": "/dev/video7"})
    elif not devices and os.path.exists("/dev/video6"):
        devices.append({"name": "Integrated Webcam", "device": "/dev/video6"})
    return devices

def find_usb_authorized(dev=None):
    if dev:
        try:
            udev_out = subprocess.check_output(["udevadm", "info", "-q", "path", "-n", dev], text=True).strip()
            parts = udev_out.split("/")
            for p in parts:
                if re.match(r"^\d+-\d+(\.\d+)*$", p):
                    auth_path = f"/sys/bus/usb/devices/{p}/authorized"
                    if os.path.exists(auth_path):
                        return auth_path
        except Exception:
            pass
    if os.path.exists("/sys/bus/usb/devices/1-4/authorized"):
        return "/sys/bus/usb/devices/1-4/authorized"
    return None

def set_privacy(block=True, dev=None):
    auth = find_usb_authorized(dev)
    if auth:
        val = "0" if block else "1"
        try:
            with open(auth, "w") as f:
                f.write(val)
            return {"status": "ok", "blocked": block}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    return {"status": "error", "error": "authorized file not found"}

def get_controls(dev=None):
    if not dev:
        devs = get_devices()
        dev = devs[0]["device"] if devs else "/dev/video7"
    ctrls = {}
    try:
        out = subprocess.check_output(["v4l2-ctl", "-d", dev, "--list-ctrls"], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("User Controls") or line.startswith("Camera Controls"):
                continue
            m = re.match(r"([a-z0-9_]+)\s+0x[0-9a-f]+\s+\(([a-z]+)\)\s*:(.*)", line)
            if m:
                name, ctype, rest = m.groups()
                data = {"type": ctype}
                for pair in re.finditer(r"([a-z_]+)=(-?\d+)", rest):
                    k, v = pair.groups()
                    data[k] = int(v)
                if "value" in data:
                    ctrls[name] = data
    except Exception:
        pass
    return ctrls

def set_controls(dev, pairs):
    args = ["v4l2-ctl", "-d", dev]
    for p in pairs:
        args.extend(["-c", p])
    subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def apply_preset(dev, preset_name):
    if preset_name not in PRESETS:
        return
    p = PRESETS[preset_name]
    pairs = [f"{k}={v}" for k, v in p.items()]
    set_controls(dev, pairs)

def monitor_stream():
    while True:
        try:
            devices = get_devices()
            current_dev = devices[0]["device"] if devices else "/dev/video7"
            in_use = is_camera_in_use()
            ctrls = get_controls(current_dev) if in_use else {}
            data = {
                "devices": devices,
                "current": current_dev,
                "controls": ctrls,
                "in_use": in_use
            }
            print(json.dumps(data), flush=True)
        except Exception:
            pass
        time.sleep(1.0)

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "get"
    dev = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2].startswith("/dev/") else None

    if cmd == "monitor":
        monitor_stream()
    elif cmd == "devices":
        print(json.dumps(get_devices()))
    elif cmd == "get":
        devices = get_devices()
        current_dev = dev or (devices[0]["device"] if devices else "/dev/video7")
        ctrls = get_controls(current_dev)
        in_use = is_camera_in_use()
        print(json.dumps({
            "devices": devices,
            "current": current_dev,
            "controls": ctrls,
            "in_use": in_use
        }))
    elif cmd == "set":
        devs = get_devices()
        dev_target = dev or (devs[0]["device"] if devs else "/dev/video7")
        pairs = sys.argv[3:] if dev else sys.argv[2:]
        set_controls(dev_target, pairs)
        print(json.dumps({"status": "ok"}))
    elif cmd == "preset":
        devs = get_devices()
        dev_target = dev or (devs[0]["device"] if devs else "/dev/video7")
        preset_name = sys.argv[3] if dev else sys.argv[2]
        apply_preset(dev_target, preset_name)
        print(json.dumps({"status": "ok", "preset": preset_name}))
    elif cmd == "privacy":
        state_str = sys.argv[3] if dev else sys.argv[2]
        block = state_str in ("1", "true", "on", "block")
        res = set_privacy(block, dev)
        print(json.dumps(res))

if __name__ == "__main__":
    main()
