"""
=========================================================================================
YOLOv1 Prediction and Post-processing Module
=========================================================================================
Purpose:
This script contains the core logic for processing the raw output of a YOLOv1 model.
Neural networks produce tensors (multi-dimensional arrays of numbers), and this module's
job is to translate that raw tensor into human-understandable results, such as bounding
boxes, class labels, and confidence scores for each detected object.

Key Functions:
- `findboxes`: Decodes the raw network output tensor into a list of potential bounding boxes.
- `process_box`: Applies a confidence threshold, scales the box coordinates to the original
  image size, and performs Non-Max Suppression (NMS) to filter out duplicate detections.
- `postprocess`: The main function that orchestrates the entire post-processing pipeline,
  draws the final bounding boxes on the image, and saves the result.
=========================================================================================
"""

from ...utils.im_transform import imcv2_recolor, imcv2_affine_trans
from ...utils.box import BoundBox, box_iou, prob_compare
import numpy as np
import cv2
import os
import json
from ...cython_utils.cy_yolo_findboxes import yolo_box_constructor

def _fix(obj, dims, scale, offs):
    """Helper function to adjust bounding box coordinates during data augmentation."""
    for i in range(1, 5):
        dim = dims[(i + 1) % 2]
        off = offs[(i + 1) % 2]
        obj[i] = int(obj[i] * scale - off)
        obj[i] = max(min(obj[i], dim), 0)

def resize_input(self, im):
    """
    Resizes the input image to the dimensions required by the YOLO model's config.
    Also normalizes pixel values to the range [0, 1] and reorders color channels
    from BGR (OpenCV's default) to RGB.
    """
    h, w, c = self.meta['inp_size']
    imsz = cv2.resize(im, (w, h))
    imsz = imsz / 255.
    imsz = imsz[:,:,::-1] # BGR -> RGB
    return imsz

def process_box(self, b, h, w, threshold):
    """
    Processes a single bounding box prediction. It checks if the confidence score
    is above the threshold and calculates the final coordinates and label.
    """
    # Find the class with the highest probability for this box
    max_indx = np.argmax(b.probs)
    max_prob = b.probs[max_indx]
    label = self.meta['labels'][max_indx]

    # Discard the box if its confidence is below the threshold
    if max_prob > threshold:
        # Convert relative coordinates (0-1) to absolute pixel coordinates
        left = int((b.x - b.w / 2.) * w)
        right = int((b.x + b.w / 2.) * w)
        top = int((b.y - b.h / 2.) * h)
        bot = int((b.y + b.h / 2.) * h)

        # Clamp coordinates to the image boundaries to prevent errors
        if left < 0: left = 0
        if right > w - 1: right = w - 1
        if top < 0: top = 0
        if bot > h - 1: bot = h - 1

        return (left, right, top, bot, label, max_indx, max_prob)
    return None

def findboxes(self, net_out):
    """
    This is the crucial step of interpreting the network's raw output tensor.
    It calls a Cython-optimized function to efficiently decode the grid-based
    predictions of YOLO into a list of bounding box objects.
    """
    meta = self.meta
    threshold = self.FLAGS.threshold

    # yolo_box_constructor is a C-compiled function for speed
    boxes = yolo_box_constructor(meta, net_out, threshold)
    return boxes

def preprocess(self, im, allobj=None):
    """
    Prepares an image for the network. If training, it applies data augmentation
    (scaling, translation, flipping, color shifts) to make the model more robust.
    """
    if not isinstance(im, np.ndarray):
        im = cv2.imread(im)

    # Augment data only during training
    if allobj is not None:
        result = imcv2_affine_trans(im)
        im, dims, trans_param = result
        scale, offs, flip = trans_param
        # Adjust ground-truth bounding boxes to match the augmented image
        for obj in allobj:
            _fix(obj, dims, scale, offs)
            if flip:
                obj_1_ = obj[1]
                obj[1] = dims[0] - obj[3]
                obj[3] = dims[0] - obj_1_
        im = imcv2_recolor(im)

    im = self.resize_input(im)
    return im

def postprocess(self, net_out, im, save=True):
    """
    The final step: takes the network output, finds boxes, draws them on the
    original image, and saves the result.
    """
    meta = self.meta
    threshold = self.FLAGS.threshold

    # Find all potential bounding boxes from the raw network output
    boxes = self.findboxes(net_out)

    if not isinstance(im, np.ndarray):
        imgcv = cv2.imread(im)
    else:
        imgcv = im.copy() # Work on a copy to avoid modifying the original array

    h, w, _ = imgcv.shape
    resultsForJSON = []

    # Process each found box
    for b in boxes:
        boxResults = self.process_box(b, h, w, threshold)
        if boxResults is None:
            continue # Skip if confidence was too low

        left, right, top, bot, mess, max_indx, confidence = boxResults
        thick = int((h + w) / 400) # Dynamic thickness for the bounding box

        # If JSON output is enabled, store results instead of drawing
        if self.FLAGS.json:
            resultsForJSON.append({
                "label": mess,
                "confidence": float(f'{confidence:.2f}'),
                "topleft": {"x": left, "y": top},
                "bottomright": {"x": right, "y": bot}
            })
            continue

        # Draw the rectangle and the label on the image
        cv2.rectangle(imgcv, (left, top), (right, bot), meta['colors'][max_indx], thick)
        cv2.putText(imgcv, mess, (left, top - 12), cv2.FONT_HERSHEY_SIMPLEX, 1e-3 * h, meta['colors'][max_indx], thick // 2)

    # Save the output if not disabled
    if not save:
        return imgcv

    # Handle file saving
    outfolder = os.path.join(self.FLAGS.imgdir, 'out')
    os.makedirs(outfolder, exist_ok=True) # Ensure the output directory exists
    img_name = os.path.join(outfolder, os.path.basename(im))

    if self.FLAGS.json:
        # Save results as a JSON file
        textFile = os.path.splitext(img_name)[0] + ".json"
        with open(textFile, 'w') as f:
            json.dump(resultsForJSON, f, indent=4)
    else:
        # Save the image with drawn boxes
        cv2.imwrite(img_name, imgcv)
