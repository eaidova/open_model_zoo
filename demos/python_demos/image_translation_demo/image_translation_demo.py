"""
 Copyright (C) 2020 Intel Corporation
 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at
      http://www.apache.org/licenses/LICENSE-2.0
 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
"""

import logging as log
import sys
import os
from argparse import ArgumentParser, SUPPRESS

import cv2
import numpy as np
from openvino.inference_engine import IECore

from image_translation_demo.models import CocosnetModel, SegmentationModel
from image_translation_demo.preprocessing import *
from image_translation_demo.postprocessing import postprocess, save_result


def build_argparser():
    parser = ArgumentParser(add_help=False)
    args = parser.add_argument_group('Options')
    args.add_argument('-h', '--help', action='help', default=SUPPRESS,
                      help='Show this help message and exit.')
    args.add_argument("-m_trn", "--translation_model",
                      help="Required. Path to an .xml file with a trained translation model",
                      required=True, type=str)
    args.add_argument("-m_seg", "--segmentation_model",
                      help="Optional. Path to an .xml file with a trained semantic segmentation model",
                      type=str)
    args.add_argument("-ii", "--input_images",
                      help="Optional. Path to a folder with input images or path to a input image",
                      type=str)
    args.add_argument("-is", "--input_semantics",
                      help="Optional. Path to a folder with semantic images or path to a semantic image",
                      type=str)
    args.add_argument("-ri", "--reference_images",
                      help="Required. Path to a folder with reference images or path to a reference image",
                      required=True, type=str)
    args.add_argument("-rs", "--reference_semantics",
                      help="Optional. Path to a folder with reference semantics or path to a reference semantic",
                      type=str)
    args.add_argument("-o", "--output_dir", help="Required. Path to a folder where output files will be saved",
                      required=True, type=str)
    args.add_argument("-d", "--device",
                      help="Optional. Specify the target device to infer on; CPU, GPU, FPGA, HDDL or MYRIAD is "
                           "acceptable. Default value is CPU",
                      default="CPU", type=str)
    return parser


def get_files(path):
    if path is None:
        return []
    if os.path.isdir(path):
        file_paths = [os.path.join(path, file) for file in os.listdir(path) if os.path.isfile(os.path.join(path, file))]
        return sorted(file_paths)
    return [path]


def get_mask_from_image(image, model):
    image = preprocess_for_seg_model(image, input_size=model.input_size)
    res = model.infer(image)
    mask = np.argmax(res, axis=1)
    mask = np.squeeze(mask, 0)
    return mask + 1


def main():
    log.basicConfig(format="[ %(levelname)s ] %(message)s", level=log.INFO, stream=sys.stdout)
    args = build_argparser().parse_args()

    log.info("Creating CoCosNet Model")
    ie_core = IECore()

    gan_model = CocosnetModel(ie_core, args.translation_model,
                              args.translation_model.replace(".xml", ".bin"),
                              args.device)
    seg_model = SegmentationModel(ie_core, args.segmentation_model,
                                  args.segmentation_model.replace(".xml", ".bin"),
                                  args.device) if args.segmentation_model else None

    log.info("Preparing input data")
    input_data = []
    use_seg = bool(args.input_images) and bool(args.segmentation_model)
    assert use_seg ^ (bool(args.input_semantics) and bool(args.reference_semantics)), "Don't know where to get data"
    input_images = get_files(args.input_images)
    input_semantics = get_files(args.input_semantics)
    reference_images = get_files(args.reference_images)
    reference_semantics = get_files(args.reference_semantics)
    number_of_objects = len(reference_images)

    if use_seg:
        samples = [input_images, number_of_objects * [''], reference_images, number_of_objects * ['']]
    else:
        samples = [number_of_objects * [''], input_semantics, reference_images, reference_semantics]
    for input_img, input_sem, ref_img, ref_sem in zip(*samples):
        if use_seg:
            input_sem = get_mask_from_image(cv2.imread(input_img), seg_model)
            ref_sem = get_mask_from_image(cv2.imread(ref_img), seg_model)
        else:
            input_sem = cv2.imread(input_sem, cv2.IMREAD_GRAYSCALE)
            ref_sem = cv2.imread(ref_sem, cv2.IMREAD_GRAYSCALE)
        input_sem = preprocess_semantics(input_sem, input_size=gan_model.input_semantic_size)
        ref_img = preprocess_image(cv2.imread(ref_img), input_size=gan_model.input_image_size)
        ref_sem = preprocess_semantics(ref_sem, input_size=gan_model.input_semantic_size)
        input_dict = {
            'input_semantics': input_sem,
            'reference_image': ref_img,
            'reference_semantics': ref_sem
        }
        input_data.append(input_dict)

    log.info("Inference for input")
    outs = [gan_model.infer(**data) for data in input_data]

    log.info("Postprocessing for result")
    results = [postprocess(out) for out in outs]

    save_result(results, args.output_dir)
    log.info("Result image was saved to {}".format(args.output_dir))


if __name__ == '__main__':
    sys.exit(main() or 0)
