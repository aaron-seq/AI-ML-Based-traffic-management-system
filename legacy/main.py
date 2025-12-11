# main.py

"""
=========================================================================================
Main Entry Point for the AI-Powered Traffic Management System
=========================================================================================
Purpose:
This script orchestrates the entire application. It performs the following steps:
1.  Parses command-line arguments to determine the operational mode (with or without
    real-time vehicle detection).
2.  If detection is enabled, it invokes the VehicleDetector to analyze an image of
    an intersection and count the vehicles in each lane.
3.  Initializes the core simulation components:
    -   TrafficManager: The brain of the simulation, handling signal logic and vehicle movement.
    -   SimulationGUI: The visual engine, responsible for rendering everything on the screen.
    -   ArduinoConnector: Manages the (optional) communication with a physical traffic light.
4.  Starts the main simulation loop.
=========================================================================================
"""

import argparse
import json
import os
import sys

# Import custom modules
from vehicle_detector import VehicleDetector
from traffic_manager import TrafficManager
from simulation_gui import SimulationGUI
from arduino import ArduinoConnector
import config

def main():
    """
    Main function to run the traffic management system.
    """
    # --- 1. Argument Parsing ---
    # Setup a parser to handle command-line arguments, allowing the user to
    # customize the simulation's behavior upon launch.
    parser = argparse.ArgumentParser(description="AI-Powered Traffic Management System")
    parser.add_argument(
        '--use-detection',
        action='store_true',  # Makes this a flag; if present, its value is True.
        help="Enable real-time vehicle detection to set initial traffic density."
    )
    parser.add_argument(
        '--image-path',
        type=str,
        default=os.path.join('test_images', '1.jpg'),
        help="Path to the intersection image to be analyzed for vehicle detection."
    )
    args = parser.parse_args()

    # Set default vehicle counts. These are used if detection is disabled.
    vehicle_counts = {'right': 8, 'left': 12, 'up': 7, 'down': 9}

    # --- 2. Vehicle Detection Stage (Optional) ---
    if args.use_detection:
        print("--- Vehicle Detection Mode Enabled ---")

        # Pre-flight checks for necessary files
        if not os.path.exists(config.MODEL_WEIGHTS):
            print("\n[FATAL ERROR] Model weights file not found!")
            print(f"Please download 'yolov2.weights' (approx. 200MB) from an official source")
            print(f"and place it in the '{os.path.join(config.BASE_DIR, 'bin')}' directory.")
            sys.exit(1) # Exit if critical files are missing

        if not os.path.exists(args.image_path):
            print(f"\n[FATAL ERROR] Input image not found at the specified path: '{args.image_path}'")
            sys.exit(1)

        # Initialize and run the detector
        print("Initializing vehicle detector... (This may take a moment)")
        detector = VehicleDetector()
        vehicle_counts = detector.detect_vehicles(args.image_path)

        print("\n--- Detection Complete ---")
        print("Detected Vehicle Counts:")
        # Pretty-print the JSON results for readability
        print(json.dumps(vehicle_counts, indent=4))
        print("--------------------------\n")
    else:
        print("--- Running in Default Simulation Mode ---")
        print("Using default vehicle counts. To use the AI model, run with the --use-detection flag.")
        print(json.dumps(vehicle_counts, indent=4))
        print("------------------------------------------\n")


    # --- 3. Simulation Initialization Stage ---
    print("--- Initializing Traffic Simulation ---")

    # Initialize the Arduino connection if it's enabled in the config file.
    # This will handle sending signal states to the physical hardware.
    arduino_comm = ArduinoConnector() if config.ENABLE_ARDUINO else None

    # Initialize the core simulation logic engine with the determined vehicle counts.
    traffic_manager = TrafficManager(vehicle_counts)

    # Initialize the GUI engine, which will handle all the drawing.
    gui = SimulationGUI()

    # --- 4. Start Simulation Main Loop ---
    # Hand over control to the GUI's main loop, which will run until the user quits.
    gui.run_game_loop(traffic_manager, arduino_comm)

    # --- 5. Cleanup ---
    # Properly close the serial connection to the Arduino on exit.
    if arduino_comm:
        arduino_comm.close()

    print("Simulation finished. Exiting application.")

# This standard Python construct ensures that the main() function is called
# only when this script is executed directly.
if __name__ == '__main__':
    main()
