import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "."

BarWidget {
  id: root
  moduleName: "kevin.camera"

  readonly property string helperPath: Qt.resolvedUrl("camera_ctl.py").toString().replace(/^file:\/\//, "")
  readonly property color foreground: bar ? bar.barForeground : Color.foreground

  // State comes from the shared poller rather than a per-screen copy.
  readonly property string currentDevice: CameraMonitor.currentDevice
  readonly property var devices: CameraMonitor.devices
  readonly property var controls: CameraMonitor.controls
  readonly property bool active: CameraMonitor.active
  readonly property bool inUse: CameraMonitor.inUse
  readonly property bool cameraBlocked: CameraMonitor.blocked

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
    CameraMonitor.setPrivacy(!root.cameraBlocked)
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
  }

  function pushControlsToPanel() {
    if (panelLoader.item && typeof panelLoader.item.updateControls === "function") {
      panelLoader.item.updateControls(root.controls, root.devices, root.currentDevice)
    }
  }

  Connections {
    target: CameraMonitor
    function onUpdated() { root.pushControlsToPanel() }
  }

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

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
