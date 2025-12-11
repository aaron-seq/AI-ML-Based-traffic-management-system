"""
=========================================================================================
Vehicle Detector Module
=========================================================================================
Purpose:
This module contains the VehicleDetector class, which is responsible for using a
pre-trained YOLOv2 model to detect and count vehicles in a given image of an
intersection. The logic is designed to be robust and provides clear feedback.

Technology Note on 'darkflow':
This project uses 'darkflow', a library that translates Darknet's YOLO models to
TensorFlow. It was primarily built for TensorFlow 1.x. Migrating this to a more
modern framework (like TensorFlow 2.x, PyTorch, or using a library like Ultralytics'
YOLOv5/v8) would be a significant but valuable upgrade for performance, ease of use,
and future compatibility.
=========================================================================================
"""

import cv2
import json
from darkflow.net.build import TFNet
import config  # Imports settings from the central configuration file

class VehicleDetector:
    """
    A class to detect vehicles in an image using a pre-trained YOLO model.
    It identifies vehicles and categorizes them into four directional lanes
    of a standard four-way intersection.
    """

    def __init__(self):
        """
        Initializes the VehicleDetector by loading the YOLOv2 model.
        This is an expensive operation and should only be done once per session.
        """
        # Define the model configuration dictionary, pulling settings from the config file.
        # This makes the detector independent of hardcoded paths.
        options = {
            "model": config.MODEL_CFG,
            "load": config.MODEL_WEIGHTS,
            "threshold": config.DETECTION_THRESHOLD,
            "gpu": 0.7  # Allocate 70% of GPU memory if available. Set to 0.0 for CPU-only.
        }

        # Load the TensorFlow model using Darkflow's TFNet class.
        print("Loading vehicle detection model into memory...")
        self.tfnet = TFNet(options)
        print("Model loaded successfully.")

        # Define the set of vehicle labels we are interested in. Using a set provides
        # fast O(1) average time complexity for checking if a detected label is a vehicle.
        self.vehicle_labels = {'car', 'bus', 'truck', 'motorbike', 'bicycle'}

    def detect_vehicles(self, image_path):
        """
        Detects and counts vehicles in the specified image, assigning each vehicle to a lane.

        Args:
            image_path (str): The full path to the image file to be processed.

        Returns:
            dict: A dictionary containing the vehicle count for each of the four lanes
                  ('right', 'left', 'up', 'down'). Returns zero counts on failure.
        """
        try:
            # Read the image using OpenCV.
            image = cv2.imread(image_path)
            if image is None:
                # If the image cannot be read, raise a specific error.
                raise FileNotFoundError(f"Image not found or could not be read at path: {image_path}")

            # Get image dimensions to define regions of interest (ROIs).
            height, width, _ = image.shape

            # Use the loaded model to get a list of predictions from the image.
            predictions = self.tfnet.return_predict(image)

            # Define the four quadrants of the image as ROIs for each traffic lane.
            # This logic assumes a top-down or angled view of a standard intersection.
            # Format: (x_start, y_start, x_end, y_end)
            rois = {
                'right': (width // 2, 0, width, height // 2),
                'down': (width // 2, height // 2, width, height),
                'left': (0, height // 2, width // 2, height),
                'up': (0, 0, width // 2, height // 2)
            }

            # Initialize a dictionary to store the count of vehicles in each lane.
            vehicle_counts = {lane: 0 for lane in rois.keys()}

            # Iterate through each prediction returned by the model.
            for prediction in predictions:
                label = prediction['label']

                # Check if the detected object's label is in our set of vehicle types.
                if label in self.vehicle_labels:
                    # Get the bounding box coordinates.
                    top_left = prediction['topleft']
                    bottom_right = prediction['bottomright']

                    # Calculate the center point of the bounding box. This point is used
                    # to determine which ROI (lane) the vehicle belongs to.
                    center_x = (top_left['x'] + bottom_right['x']) / 2
                    center_y = (top_left['y'] + bottom_right['y']) / 2

                    # Check which ROI the center point falls into.
                    for lane, (x1, y1, x2, y2) in rois.items():
                        if x1 < center_x < x2 and y1 < center_y < y2:
                            vehicle_counts[lane] += 1
                            break  # Vehicle is assigned, move to the next prediction.

            return vehicle_counts

        except Exception as e:
            # Catch any other exceptions during the process (e.g., model errors).
            print(f"[ERROR] An unexpected error occurred during vehicle detection: {e}")
            # Return a default zero-count dictionary to prevent the application from crashing.
            return {'right': 0, 'left': 0, 'up': 0, 'down': 0}

# This block allows the script to be run directly for testing purposes.
if __name__ == '__main__':
    """
    Example of how to use the VehicleDetector class independently.
    To run: python vehicle_detector.py path/to/your/image.jpg
    """
    import argparse

    # Set up a simple command-line interface for testing.
    parser = argparse.ArgumentParser(description="Detect vehicles in an image and return counts per lane.")
    parser.add_argument("image_path", type=str, help="Path to the input image file.")
    args = parser.parse_args()

    # Check for necessary files before proceeding
    if not os.path.exists(config.MODEL_WEIGHTS) or not os.path.exists(args.image_path):
         print("[FATAL ERROR] Ensure yolov2.weights is in the /bin folder and the image path is correct.")
    else:
        # Create a detector instance and run detection.
        detector = VehicleDetector()
        counts = detector.detect_vehicles(args.image_path)

        # Print the results in a clean, human-readable JSON format.
        print("\n--- Standalone Detection Results ---")
        print(json.dumps(counts, indent=4))
        print("------------------------------------")
