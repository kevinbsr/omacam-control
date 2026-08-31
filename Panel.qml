import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "kevin.camera.panel"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  readonly property color foreground: bar ? bar.barForeground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.45)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property string helperPath: Qt.resolvedUrl("camera_ctl.py").toString().replace(/^file:\/\//, "")

  property string currentDevice: hostWidget ? hostWidget.currentDevice : "/dev/video3"
  property var devices: hostWidget ? hostWidget.devices : []
  property var controls: hostWidget ? hostWidget.controls : ({})

  // Sensor state
  property int exposureVal: 320
  property int brightnessVal: 0
  property int contrastVal: 15
  property int gammaVal: 110
  property int gainVal: 1
  property int backlightVal: 1
  property bool autoExposure: false
  property bool dynamicFps: false
  property bool cameraBlocked: hostWidget ? hostWidget.cameraBlocked : false

  readonly property var presetsMap: ({
    "balanced": {
      "auto_exposure": 1,
      "exposure_time_absolute": 320,
      "gamma": 110,
      "backlight_compensation": 1,
      "brightness": 0,
      "contrast": 15,
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
      "gain": 1,
      "exposure_dynamic_framerate": 0
    },
    "auto": {
      "auto_exposure": 3,
      "backlight_compensation": 1,
      "brightness": 0,
      "contrast": 0,
      "gamma": 100,
      "gain": 1,
      "exposure_dynamic_framerate": 0
    }
  })

  onOpenedChanged: {
    if (opened && hostWidget && hostWidget.refresh) {
      hostWidget.refresh()
    }
  }

  function open() {
    root.controller.show()
    if (hostWidget && hostWidget.refresh) hostWidget.refresh()
  }

  function close() {
    root.controller.hide()
  }

  function toggle() {
    if (root.opened) root.close()
    else root.open()
  }

  function updateControls(ctrls, devs, curDev) {
    if (devs) root.devices = devs
    if (curDev) root.currentDevice = curDev
    if (!ctrls) return
    root.controls = ctrls

    if (ctrls.exposure_time_absolute) root.exposureVal = ctrls.exposure_time_absolute.value
    if (ctrls.brightness) root.brightnessVal = ctrls.brightness.value
    if (ctrls.contrast) root.contrastVal = ctrls.contrast.value
    if (ctrls.gamma) root.gammaVal = ctrls.gamma.value
    if (ctrls.gain) root.gainVal = ctrls.gain.value
    if (ctrls.backlight_compensation) root.backlightVal = ctrls.backlight_compensation.value
    if (ctrls.auto_exposure) root.autoExposure = ctrls.auto_exposure.value === 3
    if (ctrls.exposure_dynamic_framerate) root.dynamicFps = ctrls.exposure_dynamic_framerate.value === 1
  }

  function setControl(key, val) {
    Quickshell.execDetached(["python3", root.helperPath, "set", root.currentDevice, key + "=" + val])
  }

  function applyPreset(name) {
    var p = root.presetsMap[name]
    if (p) {
      if (p.exposure_time_absolute !== undefined) root.exposureVal = p.exposure_time_absolute
      if (p.brightness !== undefined) root.brightnessVal = p.brightness
      if (p.contrast !== undefined) root.contrastVal = p.contrast
      if (p.gamma !== undefined) root.gammaVal = p.gamma
      if (p.gain !== undefined) root.gainVal = p.gain
      if (p.backlight_compensation !== undefined) root.backlightVal = p.backlight_compensation
      if (p.auto_exposure !== undefined) root.autoExposure = p.auto_exposure === 3
      if (p.exposure_dynamic_framerate !== undefined) root.dynamicFps = p.exposure_dynamic_framerate === 1
    }
    Quickshell.execDetached(["python3", root.helperPath, "preset", root.currentDevice, name])
    presetTimer.restart()
  }

  Timer {
    id: presetTimer
    interval: 300
    repeat: false
    onTriggered: {
      if (hostWidget && hostWidget.refresh) hostWidget.refresh()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.hostWidget || root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(430))
    contentHeight: panel.fittedContentHeight(panelColumn.implicitHeight, Style.space(680))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()

      ScrollView {
        id: scrollArea
        anchors.fill: parent
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: panelColumn.implicitHeight > height ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff

        Column {
          id: panelColumn
          width: scrollArea.availableWidth
          spacing: Style.space(12)

          // ---------- Hero: Camera Info ----------
          PanelHero {
            width: parent.width
            title: "Omacam Control"
            meta: root.cameraBlocked ? "Camera Blocked (Privacy)" : (root.autoExposure ? "Auto Exposure Active" : "Manual Calibrated Mode")
            foreground: root.foreground
            fontFamily: root.fontFamily
            iconComponent: Component {
              Text {
                text: root.cameraBlocked ? "󰗟" : "󰄀"
                color: root.foreground
                font.pixelSize: Style.font.display
                font.family: root.fontFamily
              }
            }
          }

          // ==================== QUICK PRESETS ====================
          PanelSectionHeader {
            text: "QUICK PRESETS"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          Grid {
            width: parent.width
            columns: 2
            spacing: Style.space(6)

            Button {
              width: (parent.width - parent.spacing) / 2
              text: "Balanced"
              iconText: "󰓎"
              foreground: root.foreground
              fontFamily: root.fontFamily
              bordered: true
              onClicked: root.applyPreset("balanced")
            }

            Button {
              width: (parent.width - parent.spacing) / 2
              text: "Low Light"
              iconText: "󰖔"
              foreground: root.foreground
              fontFamily: root.fontFamily
              bordered: true
              onClicked: root.applyPreset("night")
            }

            Button {
              width: (parent.width - parent.spacing) / 2
              text: "Bright Room"
              iconText: "󰖙"
              foreground: root.foreground
              fontFamily: root.fontFamily
              bordered: true
              onClicked: root.applyPreset("bright")
            }

            Button {
              width: (parent.width - parent.spacing) / 2
              text: "Auto"
              iconText: "󰑐"
              foreground: root.foreground
              fontFamily: root.fontFamily
              bordered: true
              onClicked: root.applyPreset("auto")
            }
          }

          PanelSeparator { foreground: root.foreground }

          // ==================== EXPOSURE & SENSOR ====================
          PanelSectionHeader {
            text: "EXPOSURE & SENSOR"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          // Exposure Slider
          Column {
            width: parent.width
            spacing: Style.space(4)

            Row {
              width: parent.width
              Item {
                width: parent.width - expValText.implicitWidth
                height: expHeader.implicitHeight
                Text {
                  id: expHeader
                  text: "Exposure Time"
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  font.bold: true
                }
              }
              Text {
                id: expValText
                text: root.autoExposure ? (String(root.exposureVal) + " (Auto)") : String(root.exposureVal)
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
              }
            }

            CameraSlider {
              width: parent.width
              bar: root.bar
              minimum: 9
              maximum: 625
              step: 5
              integer: true
              value: root.exposureVal
              onMoved: function(v) {
                root.exposureVal = Math.round(v)
                if (root.autoExposure) {
                  root.autoExposure = false
                  root.setControl("auto_exposure", 1)
                }
                root.setControl("exposure_time_absolute", Math.round(v))
              }
            }
          }

          Toggle {
            width: parent.width
            label: "Lock Manual Mode"
            description: "Locks exposure time to prevent overexposure and flickering"
            checked: !root.autoExposure
            foreground: root.foreground
            accent: Color.accent
            fontFamily: root.fontFamily
            onClicked: {
              var manual = !root.autoExposure
              root.autoExposure = manual
              root.setControl("auto_exposure", manual ? 3 : 1)
              if (!manual) {
                root.setControl("exposure_time_absolute", root.exposureVal)
              }
            }
          }

          Toggle {
            width: parent.width
            label: "Dynamic Framerate"
            description: "Reduces FPS in dark environments (leave off for smooth 30fps)"
            checked: root.dynamicFps
            foreground: root.foreground
            accent: Color.accent
            fontFamily: root.fontFamily
            onClicked: {
              var next = !root.dynamicFps
              root.dynamicFps = next
              root.setControl("exposure_dynamic_framerate", next ? 1 : 0)
            }
          }

          PanelSeparator { foreground: root.foreground }

          // ==================== IMAGE ADJUSTMENTS ====================
          PanelSectionHeader {
            text: "IMAGE ADJUSTMENTS"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          // Brightness
          Column {
            width: parent.width
            spacing: Style.space(4)
            Row {
              width: parent.width
              Item { width: parent.width - briValText.implicitWidth; height: briHeader.implicitHeight; Text { id: briHeader; text: "Brightness"; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.body; font.bold: true } }
              Text { id: briValText; text: String(root.brightnessVal); color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption; font.bold: true }
            }
            CameraSlider {
              width: parent.width
              bar: root.bar
              minimum: -64; maximum: 64; step: 1; integer: true
              value: root.brightnessVal
              onMoved: function(v) { root.brightnessVal = Math.round(v); root.setControl("brightness", Math.round(v)) }
            }
          }

          // Contrast
          Column {
            width: parent.width
            spacing: Style.space(4)
            Row {
              width: parent.width
              Item { width: parent.width - conValText.implicitWidth; height: conHeader.implicitHeight; Text { id: conHeader; text: "Contrast"; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.body; font.bold: true } }
              Text { id: conValText; text: String(root.contrastVal); color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption; font.bold: true }
            }
            CameraSlider {
              width: parent.width
              bar: root.bar
              minimum: 0; maximum: 95; step: 1; integer: true
              value: root.contrastVal
              onMoved: function(v) { root.contrastVal = Math.round(v); root.setControl("contrast", Math.round(v)) }
            }
          }

          // Gamma
          Column {
            width: parent.width
            spacing: Style.space(4)
            Row {
              width: parent.width
              Item { width: parent.width - gamValText.implicitWidth; height: gamHeader.implicitHeight; Text { id: gamHeader; text: "Gamma (Shadow Detail)"; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.body; font.bold: true } }
              Text { id: gamValText; text: String(root.gammaVal); color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption; font.bold: true }
            }
            CameraSlider {
              width: parent.width
              bar: root.bar
              minimum: 100; maximum: 300; step: 5; integer: true
              value: root.gammaVal
              onMoved: function(v) { root.gammaVal = Math.round(v); root.setControl("gamma", Math.round(v)) }
            }
          }

          // Gain
          Column {
            width: parent.width
            spacing: Style.space(4)
            Row {
              width: parent.width
              Item { width: parent.width - gaiValText.implicitWidth; height: gaiHeader.implicitHeight; Text { id: gaiHeader; text: "Digital Gain"; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.body; font.bold: true } }
              Text { id: gaiValText; text: String(root.gainVal); color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption; font.bold: true }
            }
            CameraSlider {
              width: parent.width
              bar: root.bar
              minimum: 1; maximum: 8; step: 1; integer: true
              value: root.gainVal
              onMoved: function(v) { root.gainVal = Math.round(v); root.setControl("gain", Math.round(v)) }
            }
          }

          // Backlight
          Column {
            width: parent.width
            spacing: Style.space(4)
            Row {
              width: parent.width
              Item { width: parent.width - bacValText.implicitWidth; height: bacHeader.implicitHeight; Text { id: bacHeader; text: "Backlight Compensation"; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.body; font.bold: true } }
              Text { id: bacValText; text: String(root.backlightVal); color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption; font.bold: true }
            }
            CameraSlider {
              width: parent.width
              bar: root.bar
              minimum: 0; maximum: 3; step: 1; integer: true
              value: root.backlightVal
              onMoved: function(v) { root.backlightVal = Math.round(v); root.setControl("backlight_compensation", Math.round(v)) }
            }
          }

          PanelSeparator { foreground: root.foreground }

          // ==================== PRIVACY ====================
          PanelSectionHeader {
            text: "PRIVACY"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          Toggle {
            width: parent.width
            label: "Block Camera (Privacy Shutter)"
            description: "Hardware killswitch: cuts camera feed immediately in all apps"
            checked: root.cameraBlocked
            foreground: root.foreground
            accent: Color.urgent
            fontFamily: root.fontFamily
            onClicked: {
              var next = !root.cameraBlocked
              root.cameraBlocked = next
              Quickshell.execDetached(["python3", root.helperPath, "privacy", next ? "1" : "0"])
              if (hostWidget) hostWidget.cameraBlocked = next
            }
          }
        }
      }
    }
  }
}
