"""
=========================================================================================
Central Configuration File for the AI-Powered Traffic Management System
=========================================================================================
Purpose:
This file centralizes all the key parameters and settings for the application.
By modifying values here, you can easily adjust the behavior of the simulation,
the deep learning model, and hardware connections without altering the core logic.
This approach makes the system more modular and easier to maintain.
=========================================================================================
"""

import os

# --- Project Root ---
# Determines the absolute path of the project's root directory. This ensures that
# all file paths are resolved correctly, regardless of where the script is executed from.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- AI Model Configuration (YOLOv2 via Darkflow) ---
# This section defines the paths and parameters for the vehicle detection model.
# The system uses a pre-trained YOLOv2 model, which requires a config file and weights.

# Path to the YOLOv2 configuration file which defines the neural network architecture.
MODEL_CFG = os.path.join(BASE_DIR, "cfg", "yolo-voc.cfg")

# Path to the pre-trained YOLOv2 weights file.
# IMPORTANT: This large file (~200MB) must be downloaded manually and placed in the 'bin' directory.
MODEL_WEIGHTS = os.path.join(BASE_DIR, "bin", "yolov2.weights")

# Confidence threshold for the object detection model.
# Detections with a confidence score below this value will be discarded.
# A value of 0.4 means only detections with >= 40% confidence will be considered.
DETECTION_THRESHOLD = 0.4

# --- Simulation Configuration ---
# This section controls the behavior and appearance of the Pygame simulation.

# Screen dimensions for the Pygame window.
SIM_WIDTH = 1400
SIM_HEIGHT = 800

# Base time (in milliseconds) for a green signal. This is the minimum duration
# a light will stay green, even with very low traffic.
GREEN_SIGNAL_BASE_TIME = 10000  # 10 seconds

# Fixed duration (in milliseconds) for a yellow signal.
YELLOW_SIGNAL_TIME = 2000     # 2 seconds

# --- Arduino Hardware Integration (Optional) ---
# Settings for connecting to a physical traffic light model controlled by an Arduino.

# Set to True to enable communication with the Arduino. If False, the simulation
# will run without attempting to connect to any hardware.
ENABLE_ARDUINO = False

# The serial port your Arduino is connected to.
# Examples: 'COM3' on Windows, '/dev/ttyUSB0' on Linux, '/dev/tty.usbmodem1421' on macOS.
# You can find the correct port in the Arduino IDE.
ARDUINO_PORT = 'COM3'

# The baud rate for serial communication. This must match the rate set in the Arduino sketch.
ARDUINO_BAUD_RATE = 9600

# --- Asset Paths ---
# Defines the directory where all simulation images (vehicles, signals, etc.) are stored.
ASSETS_DIR = os.path.join(BASE_DIR, "images")
