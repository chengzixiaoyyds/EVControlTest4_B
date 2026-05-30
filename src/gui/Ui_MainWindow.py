# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'main_window.ui'
##
## Created by: Qt User Interface Compiler version 6.10.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QPushButton, QSizePolicy,
    QSpacerItem, QStatusBar, QVBoxLayout, QWidget)
class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.setMinimumSize(QSize(960, 600))
        MainWindow.setStyleSheet(u"QMainWindow { background-color: #2b2b2b; }\n"
"QLabel { color: #ccc; }\n"
"QGroupBox {\n"
"    font-weight: bold; color: #aaa;\n"
"    border: 1px solid #555; border-radius: 4px;\n"
"    margin-top: 10px; padding-top: 14px;\n"
"}\n"
"QGroupBox::title {\n"
"    subcontrol-origin: margin; left: 10px; padding: 0 4px;\n"
"}\n"
"QPushButton { padding: 6px 16px; color: #ccc; background: #444;\n"
"              border: 1px solid #666; border-radius: 3px; }\n"
"QPushButton:hover { background: #555; }\n"
"QPushButton:checked { background: #600; color: #f66; }")
        self.centralWidget = QWidget(MainWindow)
        self.centralWidget.setObjectName(u"centralWidget")
        self.rootLayout = QHBoxLayout(self.centralWidget)
        self.rootLayout.setSpacing(8)
        self.rootLayout.setObjectName(u"rootLayout")
        self.rootLayout.setContentsMargins(8, 8, 8, 8)
        self.videoLabel = QLabel(self.centralWidget)
        self.videoLabel.setObjectName(u"videoLabel")
        self.videoLabel.setMinimumSize(QSize(640, 480))
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(2)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.videoLabel.sizePolicy().hasHeightForWidth())
        self.videoLabel.setSizePolicy(sizePolicy)
        self.videoLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.videoLabel.setStyleSheet(u"background: #111; border: 1px solid #444; color: #666;")

        self.rootLayout.addWidget(self.videoLabel)

        self.rightPanel = QVBoxLayout()
        self.rightPanel.setSpacing(6)
        self.rightPanel.setObjectName(u"rightPanel")
        self.connectionGroup = QGroupBox(self.centralWidget)
        self.connectionGroup.setObjectName(u"connectionGroup")
        self.connectionLayout = QHBoxLayout(self.connectionGroup)
        self.connectionLayout.setObjectName(u"connectionLayout")
        self.lblSerial = QLabel(self.connectionGroup)
        self.lblSerial.setObjectName(u"lblSerial")
        self.lblSerial.setStyleSheet(u"color: #888;")

        self.connectionLayout.addWidget(self.lblSerial)

        self.lblJoystick = QLabel(self.connectionGroup)
        self.lblJoystick.setObjectName(u"lblJoystick")
        self.lblJoystick.setStyleSheet(u"color: #888;")

        self.connectionLayout.addWidget(self.lblJoystick)

        self.connSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.connectionLayout.addItem(self.connSpacer)


        self.rightPanel.addWidget(self.connectionGroup)

        self.modeGroup = QGroupBox(self.centralWidget)
        self.modeGroup.setObjectName(u"modeGroup")
        self.modeLayout = QHBoxLayout(self.modeGroup)
        self.modeLayout.setObjectName(u"modeLayout")
        self.lblModeSlow = QLabel(self.modeGroup)
        self.lblModeSlow.setObjectName(u"lblModeSlow")
        self.lblModeSlow.setStyleSheet(u"color: #888; font-size: 13px; font-weight: bold;")

        self.modeLayout.addWidget(self.lblModeSlow)

        self.lblModeMedium = QLabel(self.modeGroup)
        self.lblModeMedium.setObjectName(u"lblModeMedium")
        self.lblModeMedium.setStyleSheet(u"color: #f80; font-size: 13px; font-weight: bold;")

        self.modeLayout.addWidget(self.lblModeMedium)

        self.lblModeFast = QLabel(self.modeGroup)
        self.lblModeFast.setObjectName(u"lblModeFast")
        self.lblModeFast.setStyleSheet(u"color: #888; font-size: 13px; font-weight: bold;")

        self.modeLayout.addWidget(self.lblModeFast)

        self.modeSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.modeLayout.addItem(self.modeSpacer)


        self.rightPanel.addWidget(self.modeGroup)

        self.clawGroup = QGroupBox(self.centralWidget)
        self.clawGroup.setObjectName(u"clawGroup")
        self.clawLayout = QHBoxLayout(self.clawGroup)
        self.clawLayout.setObjectName(u"clawLayout")
        self.lblClaw = QLabel(self.clawGroup)
        self.lblClaw.setObjectName(u"lblClaw")
        self.lblClaw.setStyleSheet(u"color: #ff0; font-weight: bold; font-size: 14px;")

        self.clawLayout.addWidget(self.lblClaw)

        self.clawSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.clawLayout.addItem(self.clawSpacer)


        self.rightPanel.addWidget(self.clawGroup)

        self.controlGroup = QGroupBox(self.centralWidget)
        self.controlGroup.setObjectName(u"controlGroup")
        self.controlLayout = QGridLayout(self.controlGroup)
        self.controlLayout.setObjectName(u"controlLayout")
        self.controlLayout.setVerticalSpacing(2)
        self.lblCtrlYName = QLabel(self.controlGroup)
        self.lblCtrlYName.setObjectName(u"lblCtrlYName")

        self.controlLayout.addWidget(self.lblCtrlYName, 0, 0, 1, 1)

        self.lblCtrlYVal = QLabel(self.controlGroup)
        self.lblCtrlYVal.setObjectName(u"lblCtrlYVal")
        self.lblCtrlYVal.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)

        self.controlLayout.addWidget(self.lblCtrlYVal, 0, 1, 1, 1)

        self.lblCtrlYUnit = QLabel(self.controlGroup)
        self.lblCtrlYUnit.setObjectName(u"lblCtrlYUnit")

        self.controlLayout.addWidget(self.lblCtrlYUnit, 0, 2, 1, 1)

        self.lblCtrlXName = QLabel(self.controlGroup)
        self.lblCtrlXName.setObjectName(u"lblCtrlXName")

        self.controlLayout.addWidget(self.lblCtrlXName, 1, 0, 1, 1)

        self.lblCtrlXVal = QLabel(self.controlGroup)
        self.lblCtrlXVal.setObjectName(u"lblCtrlXVal")
        self.lblCtrlXVal.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)

        self.controlLayout.addWidget(self.lblCtrlXVal, 1, 1, 1, 1)

        self.lblCtrlXUnit = QLabel(self.controlGroup)
        self.lblCtrlXUnit.setObjectName(u"lblCtrlXUnit")

        self.controlLayout.addWidget(self.lblCtrlXUnit, 1, 2, 1, 1)

        self.lblCtrlZName = QLabel(self.controlGroup)
        self.lblCtrlZName.setObjectName(u"lblCtrlZName")

        self.controlLayout.addWidget(self.lblCtrlZName, 2, 0, 1, 1)

        self.lblCtrlZVal = QLabel(self.controlGroup)
        self.lblCtrlZVal.setObjectName(u"lblCtrlZVal")
        self.lblCtrlZVal.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)

        self.controlLayout.addWidget(self.lblCtrlZVal, 2, 1, 1, 1)

        self.lblCtrlZUnit = QLabel(self.controlGroup)
        self.lblCtrlZUnit.setObjectName(u"lblCtrlZUnit")

        self.controlLayout.addWidget(self.lblCtrlZUnit, 2, 2, 1, 1)

        self.lblCtrlYawName = QLabel(self.controlGroup)
        self.lblCtrlYawName.setObjectName(u"lblCtrlYawName")

        self.controlLayout.addWidget(self.lblCtrlYawName, 3, 0, 1, 1)

        self.lblCtrlYawVal = QLabel(self.controlGroup)
        self.lblCtrlYawVal.setObjectName(u"lblCtrlYawVal")
        self.lblCtrlYawVal.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)

        self.controlLayout.addWidget(self.lblCtrlYawVal, 3, 1, 1, 1)

        self.lblCtrlYawUnit = QLabel(self.controlGroup)
        self.lblCtrlYawUnit.setObjectName(u"lblCtrlYawUnit")

        self.controlLayout.addWidget(self.lblCtrlYawUnit, 3, 2, 1, 1)


        self.rightPanel.addWidget(self.controlGroup)

        self.sensorGroup = QGroupBox(self.centralWidget)
        self.sensorGroup.setObjectName(u"sensorGroup")
        self.sensorLayout = QGridLayout(self.sensorGroup)
        self.sensorLayout.setObjectName(u"sensorLayout")
        self.sensorLayout.setVerticalSpacing(2)
        self.lblTempName = QLabel(self.sensorGroup)
        self.lblTempName.setObjectName(u"lblTempName")

        self.sensorLayout.addWidget(self.lblTempName, 0, 0, 1, 1)

        self.lblTempVal = QLabel(self.sensorGroup)
        self.lblTempVal.setObjectName(u"lblTempVal")

        self.sensorLayout.addWidget(self.lblTempVal, 0, 1, 1, 1)

        self.lblCurrentName = QLabel(self.sensorGroup)
        self.lblCurrentName.setObjectName(u"lblCurrentName")

        self.sensorLayout.addWidget(self.lblCurrentName, 1, 0, 1, 1)

        self.lblCurrentVal = QLabel(self.sensorGroup)
        self.lblCurrentVal.setObjectName(u"lblCurrentVal")

        self.sensorLayout.addWidget(self.lblCurrentVal, 1, 1, 1, 1)

        self.lblWaterName = QLabel(self.sensorGroup)
        self.lblWaterName.setObjectName(u"lblWaterName")

        self.sensorLayout.addWidget(self.lblWaterName, 2, 0, 1, 1)

        self.lblWaterVal = QLabel(self.sensorGroup)
        self.lblWaterVal.setObjectName(u"lblWaterVal")

        self.sensorLayout.addWidget(self.lblWaterVal, 2, 1, 1, 1)


        self.rightPanel.addWidget(self.sensorGroup)

        self.overcurrentGroup = QGroupBox(self.centralWidget)
        self.overcurrentGroup.setObjectName(u"overcurrentGroup")
        self.overcurrentLayout = QGridLayout(self.overcurrentGroup)
        self.overcurrentLayout.setObjectName(u"overcurrentLayout")
        self.overcurrentLayout.setVerticalSpacing(2)
        self.lblOcName = QLabel(self.overcurrentGroup)
        self.lblOcName.setObjectName(u"lblOcName")

        self.overcurrentLayout.addWidget(self.lblOcName, 0, 0, 1, 1)

        self.lblOcStatus = QLabel(self.overcurrentGroup)
        self.lblOcStatus.setObjectName(u"lblOcStatus")

        self.overcurrentLayout.addWidget(self.lblOcStatus, 0, 1, 1, 1)

        self.lblOcThrName = QLabel(self.overcurrentGroup)
        self.lblOcThrName.setObjectName(u"lblOcThrName")

        self.overcurrentLayout.addWidget(self.lblOcThrName, 1, 0, 1, 1)

        self.lblOcThreshold = QLabel(self.overcurrentGroup)
        self.lblOcThreshold.setObjectName(u"lblOcThreshold")

        self.overcurrentLayout.addWidget(self.lblOcThreshold, 1, 1, 1, 1)

        self.lblOcTimeName = QLabel(self.overcurrentGroup)
        self.lblOcTimeName.setObjectName(u"lblOcTimeName")

        self.overcurrentLayout.addWidget(self.lblOcTimeName, 2, 0, 1, 1)

        self.lblOcTime = QLabel(self.overcurrentGroup)
        self.lblOcTime.setObjectName(u"lblOcTime")

        self.overcurrentLayout.addWidget(self.lblOcTime, 2, 1, 1, 1)


        self.rightPanel.addWidget(self.overcurrentGroup)

        self.stopwatchGroup = QGroupBox(self.centralWidget)
        self.stopwatchGroup.setObjectName(u"stopwatchGroup")
        self.stopwatchLayout = QHBoxLayout(self.stopwatchGroup)
        self.stopwatchLayout.setObjectName(u"stopwatchLayout")
        self.lblStopwatch = QLabel(self.stopwatchGroup)
        self.lblStopwatch.setObjectName(u"lblStopwatch")

        self.stopwatchLayout.addWidget(self.lblStopwatch)

        self.swSpacer = QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.stopwatchLayout.addItem(self.swSpacer)

        self.btnStopwatch = QPushButton(self.stopwatchGroup)
        self.btnStopwatch.setObjectName(u"btnStopwatch")
        self.btnStopwatch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btnStopwatch.setMinimumSize(QSize(80, 0))

        self.stopwatchLayout.addWidget(self.btnStopwatch)

        self.btnStopwatchReset = QPushButton(self.stopwatchGroup)
        self.btnStopwatchReset.setObjectName(u"btnStopwatchReset")
        self.btnStopwatchReset.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.stopwatchLayout.addWidget(self.btnStopwatchReset)


        self.rightPanel.addWidget(self.stopwatchGroup)

        self.actionLayout = QHBoxLayout()
        self.actionLayout.setObjectName(u"actionLayout")
        self.btnSnapshot = QPushButton(self.centralWidget)
        self.btnSnapshot.setObjectName(u"btnSnapshot")
        self.btnSnapshot.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.actionLayout.addWidget(self.btnSnapshot)

        self.btnRecord = QPushButton(self.centralWidget)
        self.btnRecord.setObjectName(u"btnRecord")
        self.btnRecord.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btnRecord.setMinimumSize(QSize(100, 0))
        self.btnRecord.setCheckable(True)

        self.actionLayout.addWidget(self.btnRecord)

        self.btnResetOc = QPushButton(self.centralWidget)
        self.btnResetOc.setObjectName(u"btnResetOc")
        self.btnResetOc.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.actionLayout.addWidget(self.btnResetOc)

        self.actionSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.actionLayout.addItem(self.actionSpacer)


        self.rightPanel.addLayout(self.actionLayout)

        self.rightSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.rightPanel.addItem(self.rightSpacer)


        self.rootLayout.addLayout(self.rightPanel)

        MainWindow.setCentralWidget(self.centralWidget)
        self.statusBar = QStatusBar(MainWindow)
        self.statusBar.setObjectName(u"statusBar")
        MainWindow.setStatusBar(self.statusBar)

        self.retranslateUi(MainWindow)

        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"ROV Control Station", None))
        self.videoLabel.setText(QCoreApplication.translate("MainWindow", u"\u7b49\u5f85\u6444\u50cf\u5934...", None))
        self.connectionGroup.setTitle(QCoreApplication.translate("MainWindow", u"\u8fde\u63a5\u72b6\u6001", None))
        self.lblSerial.setText(QCoreApplication.translate("MainWindow", u"\u4e32\u53e3: \u25cb \u672a\u8fde\u63a5", None))
        self.lblJoystick.setText(QCoreApplication.translate("MainWindow", u"\u624b\u67c4: \u25cb \u672a\u8fde\u63a5", None))
        self.modeGroup.setTitle(QCoreApplication.translate("MainWindow", u"\u8fd0\u52a8\u6a21\u5f0f", None))
        self.lblModeSlow.setText(QCoreApplication.translate("MainWindow", u"\u25cb SLOW", None))
        self.lblModeMedium.setText(QCoreApplication.translate("MainWindow", u"\u25cf MEDIUM", None))
        self.lblModeFast.setText(QCoreApplication.translate("MainWindow", u"\u25cb FAST", None))
        self.clawGroup.setTitle(QCoreApplication.translate("MainWindow", u"\u5939\u722a\u72b6\u6001", None))
        self.lblClaw.setText(QCoreApplication.translate("MainWindow", u"\u5939\u7d27", None))
        self.controlGroup.setTitle(QCoreApplication.translate("MainWindow", u"\u63a7\u5236\u91cf", None))
        self.lblCtrlYName.setText(QCoreApplication.translate("MainWindow", u"Y \u63a8\u529b (\u524d\u8fdb):", None))
        self.lblCtrlYVal.setText(QCoreApplication.translate("MainWindow", u"0.00", None))
        self.lblCtrlYUnit.setText(QCoreApplication.translate("MainWindow", u"N", None))
        self.lblCtrlXName.setText(QCoreApplication.translate("MainWindow", u"X \u63a8\u529b (\u53f3\u79fb):", None))
        self.lblCtrlXVal.setText(QCoreApplication.translate("MainWindow", u"0.00", None))
        self.lblCtrlXUnit.setText(QCoreApplication.translate("MainWindow", u"N", None))
        self.lblCtrlZName.setText(QCoreApplication.translate("MainWindow", u"Z \u63a8\u529b (\u4e0b\u6f5c):", None))
        self.lblCtrlZVal.setText(QCoreApplication.translate("MainWindow", u"0.00", None))
        self.lblCtrlZUnit.setText(QCoreApplication.translate("MainWindow", u"N", None))
        self.lblCtrlYawName.setText(QCoreApplication.translate("MainWindow", u"Yaw \u626d\u77e9:", None))
        self.lblCtrlYawVal.setText(QCoreApplication.translate("MainWindow", u"0.00", None))
        self.lblCtrlYawUnit.setText(QCoreApplication.translate("MainWindow", u"N\u00b7m", None))
        self.sensorGroup.setTitle(QCoreApplication.translate("MainWindow", u"\u4f20\u611f\u5668", None))
        self.lblTempName.setText(QCoreApplication.translate("MainWindow", u"\u6e29\u5ea6:", None))
        self.lblTempVal.setText(QCoreApplication.translate("MainWindow", u"-- \u00b0C", None))
        self.lblCurrentName.setText(QCoreApplication.translate("MainWindow", u"\u7535\u6d41:", None))
        self.lblCurrentVal.setText(QCoreApplication.translate("MainWindow", u"-- A", None))
        self.lblWaterName.setText(QCoreApplication.translate("MainWindow", u"\u8fdb\u6c34:", None))
        self.lblWaterVal.setText(QCoreApplication.translate("MainWindow", u"\u6b63\u5e38", None))
        self.overcurrentGroup.setTitle(QCoreApplication.translate("MainWindow", u"\u8fc7\u6d41\u4fdd\u62a4", None))
        self.lblOcName.setText(QCoreApplication.translate("MainWindow", u"\u72b6\u6001:", None))
        self.lblOcStatus.setText(QCoreApplication.translate("MainWindow", u"\u25cf \u6b63\u5e38", None))
        self.lblOcThrName.setText(QCoreApplication.translate("MainWindow", u"\u9608\u503c:", None))
        self.lblOcThreshold.setText(QCoreApplication.translate("MainWindow", u"10.0 A", None))
        self.lblOcTimeName.setText(QCoreApplication.translate("MainWindow", u"\u7d2f\u8ba1\u8fc7\u6d41:", None))
        self.lblOcTime.setText(QCoreApplication.translate("MainWindow", u"00:00:00", None))
        self.stopwatchGroup.setTitle(QCoreApplication.translate("MainWindow", u"\u79d2\u8868", None))
        self.lblStopwatch.setText(QCoreApplication.translate("MainWindow", u"00:00:00", None))
        self.btnStopwatch.setText(QCoreApplication.translate("MainWindow", u"\u25b6 \u5f00\u59cb", None))
        self.btnStopwatchReset.setText(QCoreApplication.translate("MainWindow", u"\u21ba \u91cd\u7f6e", None))
        self.btnSnapshot.setText(QCoreApplication.translate("MainWindow", u"\u622a\u56fe", None))
        self.btnRecord.setText(QCoreApplication.translate("MainWindow", u"\u25cf \u5f55\u50cf", None))
        self.btnResetOc.setText(QCoreApplication.translate("MainWindow", u"\u91cd\u7f6e\u8fc7\u6d41\u7edf\u8ba1", None))
    # retranslateUi

