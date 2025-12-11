# arduino.py

import serial
import time
import config

class ArduinoConnector:
    """
    Manages the serial communication with an Arduino board to control
    physical traffic light LEDs.
    """
    def __init__(self):
        """
        Initializes the serial connection if enabled in the config.
        """
        self.ser = None
        if config.ENABLE_ARDUINO:
            try:
                self.ser = serial.Serial(config.ARDUINO_PORT, config.ARDUINO_BAUD_RATE, timeout=1)
                time.sleep(2)  # Wait for the connection to establish
                print(f"Successfully connected to Arduino on {config.ARDUINO_PORT}.")
            except serial.SerialException as e:
                print(f"Error: Could not connect to Arduino on {config.ARDUINO_PORT}.")
                print(f"Details: {e}")
                print("Running in simulation-only mode.")
                self.ser = None

    def send_signal_state(self, signal_states):
        """
        Sends the current state of all traffic signals to the Arduino.

        The message format is a single string like "RGYR" where each character
        represents the state of a lane in the order: right, down, left, up.
        'R' = Red, 'G' = Green, 'Y' = Yellow.

        Args:
            signal_states (dict): A dictionary of lane-to-color mappings.
        """
        if not self.ser:
            return

        try:
            # Define the order of lanes to match the Arduino sketch's expectation
            lane_order = ['right', 'down', 'left', 'up']
            
            # Build the command string
            command = ""
            for lane in lane_order:
                color = signal_states.get(lane, 'red') # Default to red if lane not found
                if color == 'green':
                    command += 'G'
                elif color == 'yellow':
                    command += 'Y'
                else:
                    command += 'R'
            
            # Send the command string with a newline character as a terminator
            self.ser.write((command + '\n').encode('utf-8'))
            # print(f"Sent to Arduino: {command}") # Uncomment for debugging

        except serial.SerialException as e:
            print(f"Error writing to Arduino: {e}")
            # Attempt to close the connection if it fails
            self.ser.close()
            self.ser = None

    def close(self):
        """
        Closes the serial connection if it is open.
        """
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("Arduino connection closed.")

