import serial.tools.list_ports
import sys
import os
import re  # sanitize characters that are illegal in file names

# Force pyqtgraph to use PyQt5
os.environ["PYQTGRAPH_QT_LIB"] = "PyQt5"

import serial
import csv
import time
from datetime import datetime
import pyqtgraph as pg
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

class CalibrationDialog(QDialog):
    # --- Calibration dialog ---
    def __init__(self, dashboard, parent=None):
        super().__init__(parent)
        self.dashboard = dashboard
        self.setWindowTitle("Calibration Manager")
        self.setStyleSheet("background-color: #1E1E1E; color: #E0E0E0;")
        self.setMinimumWidth(500)
        self.setMinimumHeight(350)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        raw_group = QGroupBox("Add Calibration Point")
        raw_layout = QHBoxLayout()

        self.btn_read_raw = QPushButton("Read Current Raw")
        self.btn_read_raw.setFixedWidth(140)
        self.btn_read_raw.setStyleSheet("background-color: #1565C0; padding: 5px; border-radius: 3px;")
        self.btn_read_raw.clicked.connect(self.on_read_raw)

        self.edit_raw = QLineEdit()
        self.edit_raw.setPlaceholderText("raw value (auto-filled by the button above)")
        self.edit_raw.setStyleSheet("background-color: #2A2A2A; padding: 4px; border: 1px solid #444;")

        self.edit_weight = QLineEdit()
        self.edit_weight.setPlaceholderText("Known weight (g)")
        self.edit_weight.setStyleSheet("background-color: #2A2A2A; padding: 4px; border: 1px solid #444;")

        raw_layout.addWidget(self.btn_read_raw)
        raw_layout.addWidget(self.edit_raw)
        raw_layout.addWidget(self.edit_weight)
        raw_group.setLayout(raw_layout)

        self.btn_add = QPushButton("Add This Point (A)")
        self.btn_add.setStyleSheet("background-color: #2E7D32; padding: 6px; border-radius: 3px; font-weight: bold;")
        self.btn_add.clicked.connect(self.on_add_point)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Raw", "Weight (g)"])
        self.table.setStyleSheet("QTableWidget { background-color: #2A2A2A; } QHeaderView::section { background-color: #333; }")
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(150)

        btn_layout = QHBoxLayout()
        self.btn_list = QPushButton("List All (L)")
        self.btn_save = QPushButton("Save to Device (S)")
        self.btn_clear = QPushButton("Reset Default (C)")

        for btn in [self.btn_list, self.btn_save, self.btn_clear]:
            btn.setStyleSheet("background-color: #333; padding: 5px; border-radius: 3px;")

        self.btn_list.clicked.connect(self.on_list)
        self.btn_save.clicked.connect(self.on_save)
        self.btn_clear.clicked.connect(self.on_clear)

        btn_layout.addWidget(self.btn_list)
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_clear)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumHeight(80)
        self.log_edit.setStyleSheet("background-color: #121212; color: #888; font-size: 11px;")

        layout.addWidget(raw_group)
        layout.addWidget(self.btn_add)
        layout.addWidget(QLabel("Calibration points:"))
        layout.addWidget(self.table)
        layout.addLayout(btn_layout)
        layout.addWidget(self.log_edit)

    def on_read_raw(self):
        if self.dashboard.ser and self.dashboard.ser.is_open:
            self.dashboard.send_cmd("R")
            self.log("Requested raw reading, waiting for the device...")
        else:
            self.log("Device not connected")

    def on_add_point(self):
        raw_text = self.edit_raw.text().strip()
        weight_text = self.edit_weight.text().strip()
        if not raw_text or not weight_text:
            self.log("Please fill in both raw and weight")
            return
        cmd = f"A {raw_text} {weight_text}"
        self.dashboard.send_cmd(cmd)
        self.log(f"Sent: {cmd}")

    def on_list(self):
        self.dashboard.send_cmd("L")
        self.log("Sent: L")

    def on_save(self):
        self.dashboard.send_cmd("S")
        self.log("Sent: S")

    def on_clear(self):
        self.dashboard.send_cmd("C")
        self.log("Sent: C")

    def log(self, msg):
        self.log_edit.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def update_table(self, points):
        self.table.setRowCount(len(points))
        for i, (raw, weight) in enumerate(points):
            self.table.setItem(i, 0, QTableWidgetItem(str(raw)))
            self.table.setItem(i, 1, QTableWidgetItem(str(weight)))

class LabDashboard(QWidget):
    def __init__(self):
        super().__init__()

        self.ser = None
        self.serial_buffer = ""

        self.weight_data = []
        self.time_data = []
        self.start_time = 0
        self.last_save_time = -999

        self.smoothed_weight = None
        self.filter_alpha = 0.1

        self.is_recording = False
        self.file_name = ""
        self.cal_dialog = None

        self.init_ui()
        self.scan_ports()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_data)

    def init_ui(self):
        self.setWindowTitle("Laboratory Sample Mass Monitoring System")
        self.setStyleSheet("background-color: #121212; color: #E0E0E0;")
        self.resize(1100, 750)

        main_layout = QHBoxLayout()
        left_panel = QVBoxLayout()

        self.title = QLabel("Real-time Mass Monitoring")
        self.title.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))
        self.title.setAlignment(Qt.AlignCenter)

        self.lcd = QLabel("0.000")
        self.lcd.setFont(QFont("Arial", 75, QFont.Bold))
        self.lcd.setStyleSheet("color: #00E676; margin: 10px 0;")
        self.lcd.setAlignment(Qt.AlignCenter)

        self.unit = QLabel("Unit: gram (g)")
        self.unit.setAlignment(Qt.AlignCenter)

        # Serial communication settings
        serial_group = QGroupBox("Serial Settings")
        serial_group.setStyleSheet("QGroupBox { border: 1px solid #444; border-radius: 5px; margin-top: 1ex; font-weight: bold; } QGroupBox::title { subcontrol-origin: margin; left: 10px; }")
        serial_layout = QGridLayout()

        self.combo_ports = QComboBox()
        self.combo_ports.setStyleSheet("background-color: #333; padding: 5px; border-radius: 3px;")

        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.setStyleSheet("background-color: #424242; padding: 5px; border-radius: 3px;")
        self.btn_refresh.clicked.connect(self.scan_ports)

        self.combo_baud = QComboBox()
        self.combo_baud.addItems(['9600', '38400', '57600', '115200', '256000'])
        self.combo_baud.setCurrentText('115200')
        self.combo_baud.setStyleSheet("background-color: #333; padding: 5px; border-radius: 3px;")

        self.btn_connect = QPushButton("Connect Device (Bluetooth/Serial)")
        self.btn_connect.setFixedHeight(40)
        self.btn_connect.setStyleSheet("background-color: #1565C0; border-radius: 5px; font-weight: bold; font-size: 13px;")

        serial_layout.addWidget(QLabel("Port:"), 0, 0)
        serial_layout.addWidget(self.combo_ports, 0, 1)
        serial_layout.addWidget(self.btn_refresh, 0, 2)
        serial_layout.addWidget(QLabel("Baud rate:"), 1, 0)
        serial_layout.addWidget(self.combo_baud, 1, 1, 1, 2)
        serial_layout.addWidget(self.btn_connect, 2, 0, 1, 3)
        serial_group.setLayout(serial_layout)

        # Control & storage panel
        action_group = QGroupBox("Control & Storage")
        action_group.setStyleSheet("QGroupBox { border: 1px solid #444; border-radius: 5px; margin-top: 1ex; font-weight: bold; } QGroupBox::title { subcontrol-origin: margin; left: 10px; }")
        action_layout = QVBoxLayout()

        self.btn_tare = QPushButton("⚖️ Tare Sensor")

        # Session-name input for the CSV file name
        name_layout = QHBoxLayout()
        self.edit_filename = QLineEdit()
        self.edit_filename.setPlaceholderText("Optional: session name (e.g. sample1_evaporation)")
        self.edit_filename.setStyleSheet("background-color: #2A2A2A; padding: 5px; border: 1px solid #555; border-radius: 3px;")
        name_layout.addWidget(QLabel("Session name:"))
        name_layout.addWidget(self.edit_filename)

        self.btn_record = QPushButton("▶ Start Monitoring")
        self.btn_calibrate = QPushButton("⚙️ Calibration Manager")
        self.btn_save = QPushButton("📁 Open Data Folder")

        for btn in [self.btn_tare, self.btn_record, self.btn_calibrate, self.btn_save]:
            btn.setFixedHeight(40)
            btn.setStyleSheet("background-color: #333; border-radius: 5px; font-weight: bold; font-size: 13px;")

        self.btn_tare.setStyleSheet("background-color: #E65100; border-radius: 5px; font-weight: bold; font-size: 13px;")
        self.btn_record.setStyleSheet("background-color: #2E7D32; border-radius: 5px; font-weight: bold; font-size: 14px;")

        self.btn_calibrate.clicked.connect(self.open_calibration)
        self.btn_record.clicked.connect(self.toggle_recording)

        interval_layout = QHBoxLayout()
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(1, 600)
        self.spin_interval.setValue(1)
        self.spin_interval.setStyleSheet("QSpinBox { background-color: #333; padding: 5px; }")
        interval_layout.addWidget(QLabel("Record/plot interval (s):"))
        interval_layout.addWidget(self.spin_interval)

        action_layout.addWidget(self.btn_tare)
        action_layout.addLayout(name_layout)
        action_layout.addWidget(self.btn_record)
        action_layout.addLayout(interval_layout)
        action_layout.addWidget(self.btn_calibrate)
        action_layout.addWidget(self.btn_save)
        action_group.setLayout(action_layout)

        # Log area
        self.status_log = QTextEdit()
        self.status_log.setReadOnly(True)
        self.status_log.setStyleSheet("background-color: #1E1E1E; font-size: 12px; color: #888; border: 1px solid #333;")

        # Assemble the left panel
        left_panel.addWidget(self.title)
        left_panel.addWidget(self.lcd)
        left_panel.addWidget(self.unit)
        left_panel.addWidget(serial_group)
        left_panel.addWidget(action_group)
        left_panel.addWidget(QLabel("System log:"))
        left_panel.addWidget(self.status_log)

        # Plot area on the right
        right_panel = QVBoxLayout()
        self.plot_widget = pg.PlotWidget(title="Mass vs. Time")
        self.plot_widget.setBackground('#121212')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel('left', 'Mass (g)')
        self.plot_widget.setLabel('bottom', 'Elapsed Time (s)')

        self.curve = self.plot_widget.plot(pen=pg.mkPen(color='#00E676', width=2))
        right_panel.addWidget(self.plot_widget)

        main_layout.addLayout(left_panel, 1)
        main_layout.addLayout(right_panel, 3)
        self.setLayout(main_layout)

        # Signal connections
        self.btn_connect.clicked.connect(self.toggle_serial)
        self.btn_tare.clicked.connect(self.tare_device)
        self.btn_save.clicked.connect(lambda: os.startfile(os.getcwd()))

    def scan_ports(self):
        self.combo_ports.clear()
        ports = serial.tools.list_ports.comports()
        for p in ports:
            self.combo_ports.addItem(p.device)
        if self.combo_ports.count() == 0:
            self.combo_ports.addItem("No serial ports found")
            self.log("No serial devices detected, please check the connection")

    def toggle_serial(self):
        if self.ser is None or not self.ser.is_open:
            port = self.combo_ports.currentText()
            if port == "No serial ports found" or port == "":
                self.log("Error: please select a valid serial port first")
                return

            baud = int(self.combo_baud.currentText())
            try:
                self.ser = serial.Serial(port, baud, timeout=0)
                self.btn_connect.setText("🔌 Disconnect")
                self.btn_connect.setStyleSheet("background-color: #D32F2F; border-radius: 5px; font-weight: bold; font-size: 13px;")
                self.combo_ports.setEnabled(False)
                self.combo_baud.setEnabled(False)

                self.log(f"Connected to {port}. Streaming live mass.")
                self.serial_buffer = ""
                self.timer.start(50)
            except Exception as e:
                self.log(f"Connection failed: {str(e)}")
        else:
            if self.is_recording:
                self.toggle_recording()

            self.timer.stop()
            self.ser.close()
            self.ser = None
            self.btn_connect.setText("Connect Device (Bluetooth/Serial)")
            self.btn_connect.setStyleSheet("background-color: #1565C0; border-radius: 5px; font-weight: bold; font-size: 13px;")
            self.combo_ports.setEnabled(True)
            self.combo_baud.setEnabled(True)
            self.log("Disconnected")

    def toggle_recording(self):
        if not self.ser or not self.ser.is_open:
            self.log("Action failed: connect the sensor device first!")
            QMessageBox.warning(self, "Warning", "Connect the sensor device before starting monitoring.")
            return

        if not self.is_recording:
            self.is_recording = True

            self.weight_data.clear()
            self.time_data.clear()
            self.curve.setData(self.time_data, self.weight_data)

            self.start_time = time.time()
            self.last_save_time = -999

            # Pick up and sanitize the user-supplied session name
            custom_name = self.edit_filename.text().strip()
            # Strip characters that Windows forbids in file names
            custom_name = re.sub(r'[\\/*?:"<>|]', "", custom_name)

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            if custom_name:
                self.file_name = f"{custom_name}_{timestamp}.csv"
            else:
                self.file_name = f"Log_{timestamp}.csv"

            with open(self.file_name, 'w', newline='', encoding='utf-8-sig') as f:
                csv.writer(f).writerow(["timestamp", "time_s", "weight_g"])

            self.btn_record.setText("⏸ Stop & Save (recording...)")
            self.btn_record.setStyleSheet("background-color: #FF8F00; color: black; border-radius: 5px; font-weight: bold; font-size: 14px;")
            self.edit_filename.setEnabled(False)  # lock the name while recording
            self.log(f"▶ Monitoring started! Data will be saved to: {self.file_name}")

        else:
            self.is_recording = False
            self.btn_record.setText("▶ Start Monitoring")
            self.btn_record.setStyleSheet("background-color: #2E7D32; border-radius: 5px; font-weight: bold; font-size: 14px;")
            self.edit_filename.setEnabled(True)  # re-enable the name field
            self.log(f"⏸ Monitoring stopped! Data set saved to: {self.file_name}")

    def update_data(self):
        if not (self.ser and self.ser.is_open):
            return

        try:
            waiting = self.ser.in_waiting
            if waiting > 0:
                raw_bytes = self.ser.read(waiting)
                self.serial_buffer += raw_bytes.decode('utf-8', errors='ignore')

            if '\n' in self.serial_buffer:
                lines = self.serial_buffer.replace('\r', '').split('\n')
                self.serial_buffer = lines.pop()

                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    is_text_cmd = False
                    text_keywords = ["RAW:", "---", "OK", "ADDED", "SAVED", "CLEARED", "FULL", "NO CHANGE", "UNKNOWN", "Usage:", "raw="]
                    for kw in text_keywords:
                        if kw in line:
                            is_text_cmd = True
                            break

                    if is_text_cmd:
                        self._route_cal_response(line)
                        continue

                    try:
                        raw_weight = float(line)
                        if self.smoothed_weight is None:
                            self.smoothed_weight = raw_weight
                        else:
                            self.smoothed_weight = (self.filter_alpha * raw_weight) + ((1 - self.filter_alpha) * self.smoothed_weight)

                        final_weight = round(self.smoothed_weight, 3)
                        self.lcd.setText(f"{final_weight:.3f}")

                        if self.is_recording:
                            curr_time = round(time.time() - self.start_time, 1)
                            record_interval = self.spin_interval.value()

                            if curr_time - self.last_save_time >= record_interval:
                                self.last_save_time = curr_time
                                self.weight_data.append(final_weight)
                                self.time_data.append(curr_time)
                                self.curve.setData(self.time_data, self.weight_data)

                                with open(self.file_name, 'a', newline='', encoding='utf-8-sig') as f:
                                    csv.writer(f).writerow([datetime.now().strftime('%H:%M:%S'), curr_time, final_weight])
                    except ValueError:
                        pass

        except Exception as e:
            self.log(f"Communication error: {e}")

    def tare_device(self):
        if self.ser and self.ser.is_open:
            self.ser.write(b'T\n')
            self.smoothed_weight = 0
            self.lcd.setText("0.000")
            self.log("Tare command sent, waiting for the sensor...")
        else:
            self.log("Error: cannot tare, device not connected")

    def send_cmd(self, cmd):
        if self.ser and self.ser.is_open:
            self.ser.write((cmd + '\n').encode())
        else:
            self.log("Error: device not connected")

    def open_calibration(self):
        if self.cal_dialog is None:
            self.cal_dialog = CalibrationDialog(self)
        self.cal_dialog.show()
        self.cal_dialog.raise_()
        self.cal_dialog.activateWindow()

    def _route_cal_response(self, line):
        d = self.cal_dialog
        if d is None or not d.isVisible():
            if "RAW:" not in line:
                self.log(f"[Device] {line}")
            return
        if line.startswith("RAW:"):
            raw_str = line[4:]
            if raw_str != "ERROR":
                d.edit_raw.setText(raw_str)
                d.log(f"Raw value received: raw = {raw_str}")
            return
        if line in ("ADDED", "SAVED", "CLEARED", "FULL", "NO CHANGE", "OK") or "Usage:" in line:
            d.log(f"Device replied: {line}")
            return
        if line.startswith("--- CAL TABLE ---"):
            d._parsing_list = True
            d._parse_points = []
            d.log("Calibration table received:")
            return
        if line.startswith("--- END ---"):
            d._parsing_list = False
            d.update_table(getattr(d, "_parse_points", []))
            return
        if getattr(d, "_parsing_list", False):
            try:
                after_idx = line.index(": raw=")
                raw_part = line[after_idx + 6:].split(" weight=")
                d._parse_points.append((int(raw_part[0]), float(raw_part[1])))
            except Exception:
                pass
            d.log(line)
            return
        d.log(f"[Device] {line}")

    def log(self, text):
        self.status_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {text}")
        self.status_log.moveCursor(QTextCursor.End)

if __name__ == "__main__":
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    window = LabDashboard()
    window.show()
    sys.exit(app.exec_())
