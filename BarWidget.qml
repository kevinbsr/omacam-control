import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "kevin.camera"

  readonly property string helperPath: Qt.resolvedUrl("camera_ctl.py").toString().replace(/^file:\/\//, "")
  readonly property color foreground: bar ? bar.barForeground : Color.foreground

  property string currentDevice: "/dev/video7"
  property var devices: []
  property var controls: ({})
  property bool active: false
  property bool inUse: true
  property bool cameraBlocked: false

  // nf-md-camera (󰄀) e nf-md-camera_off (󰗟)
  readonly property string icon: cameraBlocked ? "󰗟" : "󰄀"
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false

  // On-demand visibility: only show when camera is actively streaming, or privacy blocked, or panel open
  visible: root.inUse || root.cameraBlocked || root.opened
  implicitWidth: root.visible ? button.implicitWidth : 0
  implicitHeight: root.visible ? button.implicitHeight : 0

  function open() {
    if (panelLoader.item) panelLoader.item.open()
  }

  function close() {
    if (panelLoader.item) panelLoader.item.close()
  }

  function toggle() {
    if (panelLoader.item) panelLoader.item.toggle()
  }

  function togglePrivacy() {
    var next = !root.cameraBlocked
    root.cameraBlocked = next
    Quickshell.execDetached(["python3", root.helperPath, "privacy", next ? "1" : "0"])
    if (panelLoader.item) {
      panelLoader.item.cameraBlocked = next
    }
  }

  function preset(name) {
    if (panelLoader.item) panelLoader.item.applyPreset(name)
  }

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
    if ("cameraBlocked" in target) target.cameraBlocked = root.cameraBlocked
  }

  function handleQueryResult(line) {
    var raw = String(line || "").trim()
    if (!raw) return
    try {
      var data = JSON.parse(raw)
      if (data.devices) root.devices = data.devices
      if (data.current) root.currentDevice = data.current
      if (data.in_use !== undefined) root.inUse = data.in_use
      if (data.controls) {
        root.controls = data.controls
        root.active = Object.keys(data.controls).length > 0
      }
      if (panelLoader.item && typeof panelLoader.item.updateControls === "function") {
        panelLoader.item.updateControls(root.controls, root.devices, root.currentDevice)
      }
    } catch (e) {}
  }

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Process {
    id: monitorProc
    running: true
    command: ["python3", root.helperPath, "monitor"]
    stdout: SplitParser {
      onRead: function(line) {
        root.handleQueryResult(line)
      }
    }
  }

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.icon
    active: root.opened
    tooltipText: root.cameraBlocked ? "Camera: Privacy Shutter ON (Right-click to unblock)" : "Camera: Click for controls, right-click for privacy"
    onPressed: function(b) {
      if (b === Qt.RightButton) {
        root.togglePrivacy()
      } else {
        root.toggle()
      }
    }
  }
}
