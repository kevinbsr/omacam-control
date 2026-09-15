pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io

// One poller for the whole shell.
//
// The helper's `monitor` mode is a `while True` loop that re-enumerates V4L2
// devices once a second, and the bar widget used to start its own copy. Bar
// widgets are instantiated once per screen, so plugging in two external
// displays quietly tripled the polling: three processes waking three times a
// second to read state that is identical for all of them.
//
// A singleton is instantiated once per QML engine, and every bar widget lives
// in the same Quickshell process, so the poller here is shared no matter how
// many screens are attached.
Singleton {
  id: mon

  readonly property string helperPath: Qt.resolvedUrl("camera_ctl.py").toString().replace(/^file:\/\//, "")

  // Empty until the helper reports a validated capture device.
  property string currentDevice: ""
  property var devices: []
  property var controls: ({})
  property bool active: false
  property bool inUse: true
  // Privacy shutter state as recorded by the helper, shared by every bar
  // widget and panel instead of being tracked per screen.
  property bool blocked: false
  property string blockedName: ""
  property bool privacyBusy: privacyProc.running

  signal updated()

  // Blocking needs the device: the helper disables only the USB device that
  // owns that V4L2 node. Unblocking re-authorizes the device the helper
  // recorded when it blocked, since the node is gone while blocked.
  function setPrivacy(block) {
    if (privacyProc.running) return
    if (block && !mon.currentDevice) {
      console.warn("kevin.camera: no capture device to block")
      return
    }
    mon.blocked = block
    privacyProc.command = block
      ? ["python3", mon.helperPath, "privacy", mon.currentDevice, "1"]
      : ["python3", mon.helperPath, "privacy", "0"]
    privacyProc.running = true
  }

  function ingest(line) {
    var raw = String(line || "").trim()
    // Snapshots are a few KiB; anything far larger is not ours.
    if (!raw || raw.length > 262144) return
    try {
      var data = JSON.parse(raw)
      if (data.devices) mon.devices = data.devices
      if (data.current) mon.currentDevice = data.current
      if (data.in_use !== undefined) mon.inUse = data.in_use === true
      if (data.blocked !== undefined && !privacyProc.running) mon.blocked = data.blocked === true
      if (typeof data.blocked_name === "string") mon.blockedName = data.blocked_name
      if (data.controls) {
        mon.controls = data.controls
        mon.active = Object.keys(data.controls).length > 0
      }
      mon.updated()
    } catch (e) {}
  }

  Process {
    id: privacyProc
    running: false
    stdout: StdioCollector {
      onStreamFinished: {
        var result = null
        try { result = JSON.parse(String(text || "").slice(0, 4096)) } catch (e) {}
        if (!result || result.status !== "ok") {
          console.warn("kevin.camera: privacy shutter failed:", result ? result.error : text)
          mon.blocked = !mon.blocked
        }
      }
    }
  }

  Process {
    running: true
    command: ["python3", mon.helperPath, "monitor"]
    stdout: SplitParser {
      onRead: function(line) { mon.ingest(line) }
    }
  }
}
