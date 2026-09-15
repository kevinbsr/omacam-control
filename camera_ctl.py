#!/usr/bin/env python3
"""Omacam Control helper: V4L2 discovery, sensor controls and privacy shutter.

Everything the bar polls once a second is read from sysfs or with V4L2 ioctls
on an already validated device node, so the steady-state loop spawns no
processes. The only external tool left is `fuser`, and only for cameras whose
streaming state sysfs cannot report (non-USB or bulk-transfer UVC); it runs
under a hard deadline with a capped output.

Every input is bounded before it is trusted:
  * device arguments must resolve to a V4L2 character device (major 81) that
    sysfs agrees on and whose driver reports video capture;
  * the privacy shutter only ever writes the `authorized` attribute of the USB
    device that owns that V4L2 node, after checking that the interface is USB
    video class. There is no fallback path;
  * device, control and argument counts, string lengths and file reads all
    have fixed caps.
"""
import errno
import fcntl
import json
import os
import re
import selectors
import stat
import struct
import subprocess
import sys
import time

V4L2_MAJOR = 81
VIDIOC_QUERYCAP = 0x80685600
VIDIOC_QUERYCTRL = 0xC0445624
VIDIOC_G_CTRL = 0xC008561B
VIDIOC_S_CTRL = 0xC008561C
V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_DEVICE_CAPS = 0x80000000
V4L2_CTRL_FLAG_NEXT_CTRL = 0x80000000
V4L2_CTRL_FLAG_DISABLED = 0x0001
V4L2_CTRL_FLAG_READ_ONLY = 0x0004
V4L2_CTRL_FLAG_WRITE_ONLY = 0x0040
# Control types that fit a 32-bit VIDIOC_G_CTRL value, named as v4l2-ctl does.
CTRL_TYPES = {1: "int", 2: "bool", 3: "menu", 8: "bitmask", 9: "intmenu"}

SYSFS_V4L = "/sys/class/video4linux"
USB_IFACE_CLASS_VIDEO = "0e"
USB_CLASS_HUB = "09"
USB_DEV_RE = re.compile(r"^\d+-\d+(?:\.\d+)*$")
USB_IFACE_RE = re.compile(r"^(\d+-\d+(?:\.\d+)*):\d+\.\d+$")
NODE_RE = re.compile(r"^video(\d{1,4})$")
DEV_PATH_RE = re.compile(r"^/dev/video(\d{1,4})$")
PAIR_RE = re.compile(r"^([a-z0-9_]{1,48})=(-?\d{1,10})$")

MAX_NODES = 64          # sysfs video4linux entries scanned
MAX_DEVICES = 8         # capture devices reported
MAX_CONTROLS = 64       # controls enumerated per device
MAX_PAIRS = 32          # control assignments per `set`
MAX_NAME = 64           # characters kept from driver-provided names
MAX_ARG = 256           # characters accepted per argument
SYSFS_READ_MAX = 256    # bytes read from a sysfs attribute
STATE_READ_MAX = 4096   # bytes read from the privacy state file
CMD_TIMEOUT = 2.0       # seconds an external command may run
CMD_OUTPUT_MAX = 16384  # bytes of stdout accepted from an external command
POLL_INTERVAL = 1.0

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


class HelperError(Exception):
    pass


# --- bounded primitives -----------------------------------------------------

def read_attr(path, limit=SYSFS_READ_MAX):
    try:
        with open(path, "rb") as f:
            return f.read(limit).decode("utf-8", "replace").strip()
    except OSError:
        return None


def run_bounded(argv, timeout=CMD_TIMEOUT, limit=CMD_OUTPUT_MAX):
    """Run argv with a deadline and a stdout cap. Returns (returncode, text),
    or None if it could not start, overran the deadline or the cap."""
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, close_fds=True)
    except OSError:
        return None
    deadline = time.monotonic() + timeout
    chunks, size, ok = [], 0, True
    fd = proc.stdout.fileno()
    with selectors.DefaultSelector() as sel:
        sel.register(fd, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not sel.select(remaining):
                ok = False
                break
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                ok = False
                break
            chunks.append(chunk)
    try:
        if ok:
            proc.wait(timeout=max(0.05, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        ok = False
    if not ok:
        proc.kill()
        proc.wait()
    proc.stdout.close()
    if not ok:
        return None
    return proc.returncode, b"".join(chunks).decode("utf-8", "replace")


def clean_name(raw):
    text = "".join(ch for ch in raw if ch.isprintable())
    return text.strip()[:MAX_NAME]


# --- V4L2 -------------------------------------------------------------------

def open_node(path):
    return os.open(path, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)


def query_caps(fd):
    buf = bytearray(104)
    fcntl.ioctl(fd, VIDIOC_QUERYCAP, buf)
    driver, card, bus, _version, caps, device_caps = struct.unpack_from("16s32s32sIII", buf)
    if caps & V4L2_CAP_DEVICE_CAPS:
        caps = device_caps

    def text(b):
        return clean_name(b.split(b"\0", 1)[0].decode("utf-8", "replace"))

    return {"driver": text(driver), "card": text(card), "bus": text(bus), "caps": caps}


def node_identity(node):
    """Return (dev_path, rdev) for a sysfs video4linux entry whose /dev node
    is a V4L2 character device matching sysfs, else None."""
    m = NODE_RE.match(node)
    if not m:
        return None
    dev_path = f"/dev/{node}"
    try:
        st = os.stat(dev_path)
    except OSError:
        return None
    if not stat.S_ISCHR(st.st_mode) or os.major(st.st_rdev) != V4L2_MAJOR:
        return None
    if read_attr(f"{SYSFS_V4L}/{node}/dev") != f"{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}":
        return None
    return dev_path, st.st_rdev


_caps_cache = {}


def capture_caps(node):
    """Capabilities of a capture node, cached per (node, rdev, parent) so the
    poller only opens a node when the device set changes."""
    ident = node_identity(node)
    if not ident:
        return None
    parent = os.path.realpath(f"{SYSFS_V4L}/{node}/device")
    key = (node, ident[1], parent)
    if key not in _caps_cache:
        if len(_caps_cache) > MAX_NODES:
            _caps_cache.clear()
        try:
            fd = open_node(ident[0])
            try:
                _caps_cache[key] = query_caps(fd)
            finally:
                os.close(fd)
        except OSError:
            return None
    caps = _caps_cache[key]
    return caps if caps["caps"] & V4L2_CAP_VIDEO_CAPTURE else None


def validate_device(arg):
    """Canonical /dev/videoN for a user-supplied path, or HelperError."""
    if not isinstance(arg, str) or len(arg) > MAX_ARG:
        raise HelperError("invalid device argument")
    path = os.path.realpath(arg)
    m = DEV_PATH_RE.match(path)
    if not m:
        raise HelperError(f"not a V4L2 device node: {arg}")
    node = f"video{m.group(1)}"
    if not node_identity(node):
        raise HelperError(f"not a V4L2 character device: {arg}")
    if not capture_caps(node):
        raise HelperError(f"not a video capture device: {arg}")
    return path


def physical_parent(node):
    link = f"{SYSFS_V4L}/{node}/device"
    # Loopback and other virtual devices have no parent device link.
    return os.path.realpath(link) if os.path.islink(link) else None


def get_devices():
    try:
        nodes = sorted((n for n in os.listdir(SYSFS_V4L) if NODE_RE.match(n)),
                       key=lambda n: int(n[5:]))[:MAX_NODES]
    except OSError:
        return []
    devices, seen = [], set()
    for node in nodes:
        parent = physical_parent(node)
        if not parent or parent in seen:
            continue
        caps = capture_caps(node)
        if not caps:
            continue
        seen.add(parent)
        devices.append({
            "name": caps["card"] or node,
            "device": f"/dev/{node}",
            "usb": usb_device_for(node) is not None,
        })
        if len(devices) >= MAX_DEVICES:
            break
    devices.sort(key=lambda d: 0 if d["usb"] else 1)
    return devices


def ctrl_name(raw):
    """Control label to identifier, the way v4l2-ctl derives it."""
    out, pending = [], False
    for ch in raw:
        if ch.isascii() and ch.isalnum():
            if pending:
                out.append("_")
            pending = False
            out.append(ch.lower())
        elif out:
            pending = True
    return "".join(out)[:48]


def enumerate_controls(fd):
    ctrls = {}
    ctrl_id = V4L2_CTRL_FLAG_NEXT_CTRL
    for _ in range(MAX_CONTROLS * 4):
        buf = bytearray(struct.pack("I", ctrl_id) + bytes(64))
        try:
            fcntl.ioctl(fd, VIDIOC_QUERYCTRL, buf)
        except OSError:
            break
        cid, ctype, name, lo, hi, step, default, flags = struct.unpack_from("II32siiiiI", buf)
        ctrl_id = cid | V4L2_CTRL_FLAG_NEXT_CTRL
        if ctype not in CTRL_TYPES or flags & (V4L2_CTRL_FLAG_DISABLED | V4L2_CTRL_FLAG_WRITE_ONLY):
            continue
        key = ctrl_name(name.split(b"\0", 1)[0].decode("utf-8", "replace"))
        if not key:
            continue
        value = struct.pack("Ii", cid, 0)
        vbuf = bytearray(value)
        try:
            fcntl.ioctl(fd, VIDIOC_G_CTRL, vbuf)
        except OSError:
            continue
        data = {"type": CTRL_TYPES[ctype], "id": cid, "min": lo, "max": hi, "step": step,
                "default": default, "value": struct.unpack_from("Ii", vbuf)[1],
                "read_only": bool(flags & V4L2_CTRL_FLAG_READ_ONLY)}
        ctrls[key] = data
        if len(ctrls) >= MAX_CONTROLS:
            break
    return ctrls


def get_controls(dev):
    try:
        fd = open_node(dev)
    except OSError:
        return {}
    try:
        return {k: {f: v for f, v in c.items() if f not in ("id", "read_only")}
                for k, c in enumerate_controls(fd).items()}
    finally:
        os.close(fd)


def set_controls(dev, pairs):
    """Apply name=value pairs in order. Unknown, read-only or out-of-range
    controls are skipped and reported."""
    if len(pairs) > MAX_PAIRS:
        raise HelperError(f"too many controls (max {MAX_PAIRS})")
    parsed = []
    for p in pairs:
        m = PAIR_RE.match(p) if isinstance(p, str) else None
        if not m:
            raise HelperError(f"invalid control assignment: {str(p)[:MAX_NAME]}")
        parsed.append((m.group(1), int(m.group(2))))
    applied, skipped = [], []
    fd = open_node(dev)
    try:
        ctrls = enumerate_controls(fd)
        for name, value in parsed:
            c = ctrls.get(name)
            if not c or c["read_only"] or not c["min"] <= value <= c["max"]:
                skipped.append(name)
                continue
            try:
                fcntl.ioctl(fd, VIDIOC_S_CTRL, bytearray(struct.pack("Ii", c["id"], value)))
                applied.append(name)
            except OSError:
                skipped.append(name)
    finally:
        os.close(fd)
    return {"status": "ok", "applied": applied, "skipped": skipped}


def apply_preset(dev, preset_name):
    if preset_name not in PRESETS:
        raise HelperError(f"unknown preset: {str(preset_name)[:MAX_NAME]}")
    return set_controls(dev, [f"{k}={v}" for k, v in PRESETS[preset_name].items()])


# --- streaming state --------------------------------------------------------

def usb_interface_for(node):
    parent = physical_parent(node)
    if not parent or not USB_IFACE_RE.match(os.path.basename(parent)):
        return None
    return parent


def usb_device_for(node):
    """sysfs path of the USB device that owns a V4L2 node, only if the node's
    interface is USB video class and the device is not a hub."""
    iface = usb_interface_for(node)
    if not iface or read_attr(f"{iface}/bInterfaceClass") != USB_IFACE_CLASS_VIDEO:
        return None
    usb = os.path.dirname(iface)
    name = os.path.basename(usb)
    if not USB_DEV_RE.match(name) or USB_IFACE_RE.match(os.path.basename(iface)).group(1) != name:
        return None
    if read_attr(f"{usb}/bDeviceClass") == USB_CLASS_HUB:
        return None
    if not os.path.isfile(f"{usb}/authorized"):
        return None
    return usb


def usb_streaming(usb):
    """True/False when sysfs can tell, None when it cannot.

    UVC cameras with isochronous endpoints select a non-zero alternate setting
    on their VideoStreaming interface (subclass 02) only while frames flow."""
    try:
        entries = os.listdir(usb)[:MAX_NODES]
    except OSError:
        return None
    base = os.path.basename(usb)
    known = False
    for entry in entries:
        m = USB_IFACE_RE.match(entry)
        if not m or m.group(1) != base:
            continue
        iface = f"{usb}/{entry}"
        if (read_attr(f"{iface}/bInterfaceClass") != USB_IFACE_CLASS_VIDEO
                or read_attr(f"{iface}/bInterfaceSubClass") != "02"):
            continue
        if any(read_attr(f"{iface}/{ep}/type") == "Bulk"
               for ep in os.listdir(iface)[:32] if ep.startswith("ep_")):
            return None
        alt = read_attr(f"{iface}/bAlternateSetting")
        if alt is None:
            continue
        known = True
        if alt.strip() not in ("0", ""):
            return True
    return False if known else None


def node_open_elsewhere(dev):
    res = run_bounded(["fuser", dev])
    if not res:
        return False
    rc, out = res
    me = str(os.getpid())
    return rc == 0 and any(p.rstrip("cefFrm") not in ("", me) for p in out.split()[:256])


def is_camera_in_use(devices):
    for d in devices:
        node = os.path.basename(d["device"])
        usb = usb_device_for(node)
        state = usb_streaming(usb) if usb else None
        if state is None:
            state = node_open_elsewhere(d["device"])
        if state:
            return True
    return False


# --- privacy shutter --------------------------------------------------------

def state_path():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "omacam-control", "privacy.json")


def usb_identity(usb):
    return {k: read_attr(f"{usb}/{k}") or "" for k in ("idVendor", "idProduct", "serial")}


def load_privacy_state():
    try:
        with open(state_path(), "rb") as f:
            raw = f.read(STATE_READ_MAX + 1)
    except OSError:
        return None
    try:
        data = json.loads(raw[:STATE_READ_MAX])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    usb = data.get("usb")
    if (not isinstance(usb, str) or len(usb) > MAX_ARG or not usb.startswith("/sys/devices/")
            or os.path.realpath(usb) != usb or not USB_DEV_RE.match(os.path.basename(usb))):
        return None
    ident = data.get("identity")
    if not isinstance(ident, dict) or not all(isinstance(ident.get(k), str)
                                              for k in ("idVendor", "idProduct", "serial")):
        return None
    if usb_identity(usb) != {k: ident[k] for k in ("idVendor", "idProduct", "serial")}:
        return None
    name = data.get("name")
    return {"usb": usb, "name": clean_name(name) if isinstance(name, str) else ""}


def save_privacy_state(usb, name):
    path = state_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump({"usb": usb, "identity": usb_identity(usb), "name": name}, f)
    os.replace(tmp, path)


def clear_privacy_state():
    try:
        os.unlink(state_path())
    except FileNotFoundError:
        pass


def privacy_blocked():
    state = load_privacy_state()
    if state and read_attr(f"{state['usb']}/authorized") == "0":
        return state
    return None


def write_authorized(usb, value):
    try:
        with open(f"{usb}/authorized", "w") as f:
            f.write(value)
    except OSError as e:
        hint = " (see README: the authorized attribute needs a udev rule)" if e.errno in (errno.EACCES, errno.EPERM) else ""
        raise HelperError(f"cannot write {usb}/authorized: {e.strerror}{hint}")


def set_privacy(block, dev=None):
    if block:
        if dev is None:
            candidates = [d for d in get_devices() if d["usb"]]
            if not candidates:
                raise HelperError("no USB video capture device found")
            dev, name = candidates[0]["device"], candidates[0]["name"]
        else:
            name = capture_caps(os.path.basename(dev))["card"]
        usb = usb_device_for(os.path.basename(dev))
        if not usb:
            raise HelperError(f"{dev} is not a USB video class device; no privacy shutter")
        save_privacy_state(usb, name)
        try:
            write_authorized(usb, "0")
        except HelperError:
            clear_privacy_state()
            raise
        return {"status": "ok", "blocked": True, "device": dev}

    state = load_privacy_state()
    if state:
        write_authorized(state["usb"], "1")
        clear_privacy_state()
        return {"status": "ok", "blocked": False}
    if dev is not None:
        usb = usb_device_for(os.path.basename(dev))
        if usb and read_attr(f"{usb}/authorized") == "1":
            return {"status": "ok", "blocked": False}
    raise HelperError("no camera blocked by Omacam Control")


# --- commands ---------------------------------------------------------------

def snapshot(dev=None):
    devices = get_devices()
    current = dev or (devices[0]["device"] if devices else "")
    in_use = is_camera_in_use(devices) if devices else False
    blocked = privacy_blocked()
    return {
        "devices": devices,
        "current": current,
        "controls": get_controls(current) if current and in_use else {},
        "in_use": in_use,
        "blocked": blocked is not None,
        "blocked_name": blocked["name"] if blocked else "",
    }


def monitor_stream():
    last = None
    while True:
        try:
            line = json.dumps(snapshot())
        except Exception:
            line = None
        if line and line != last:
            try:
                print(line, flush=True)
            except BrokenPipeError:
                return
            last = line
        time.sleep(POLL_INTERVAL)


def default_device():
    devices = get_devices()
    if not devices:
        raise HelperError("no video capture device found")
    return devices[0]["device"]


def main(argv):
    if len(argv) > 3 + MAX_PAIRS or any(len(a) > MAX_ARG for a in argv):
        raise HelperError("too many or too long arguments")
    cmd = argv[1] if len(argv) > 1 else "get"
    rest = argv[2:]
    dev = None
    if rest and rest[0].startswith("/"):
        dev = validate_device(rest[0])
        rest = rest[1:]

    if cmd == "monitor":
        monitor_stream()
    elif cmd == "devices":
        print(json.dumps(get_devices()))
    elif cmd == "get":
        print(json.dumps(snapshot(dev)))
    elif cmd == "set":
        print(json.dumps(set_controls(dev or default_device(), rest)))
    elif cmd == "preset":
        if len(rest) != 1:
            raise HelperError("usage: preset [/dev/videoN] <name>")
        print(json.dumps({**apply_preset(dev or default_device(), rest[0]), "preset": rest[0]}))
    elif cmd == "privacy":
        if len(rest) != 1 or rest[0] not in ("1", "0", "true", "false", "on", "off", "block", "unblock"):
            raise HelperError("usage: privacy [/dev/videoN] <1|0>")
        print(json.dumps(set_privacy(rest[0] in ("1", "true", "on", "block"), dev)))
    else:
        raise HelperError(f"unknown command: {cmd[:MAX_NAME]}")


if __name__ == "__main__":
    try:
        main(sys.argv)
    except HelperError as e:
        print(json.dumps({"status": "error", "error": str(e)}))
        sys.exit(2)
