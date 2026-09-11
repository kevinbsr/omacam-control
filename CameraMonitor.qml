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

  property string currentDevice: "/dev/video7"
  property var devices: []
  property var controls: ({})
  property bool active: false
  property bool inUse: true

  signal updated()

  function ingest(line) {
    var raw = String(line || "").trim()
    if (!raw) return
    try {
      var data = JSON.parse(raw)
      if (data.devices) mon.devices = data.devices
      if (data.current) mon.currentDevice = data.current
      if (data.in_use !== undefined) mon.inUse = data.in_use
      if (data.controls) {
        mon.controls = data.controls
        mon.active = Object.keys(data.controls).length > 0
      }
      mon.updated()
    } catch (e) {}
  }

  Process {
    running: true
    command: ["python3", mon.helperPath, "monitor"]
    stdout: SplitParser {
      onRead: function(line) { mon.ingest(line) }
    }
  }
}
