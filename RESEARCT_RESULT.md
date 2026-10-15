# Deep research: Offline, real-time camera fault detection for ADAS

Yes. There are open-source AI models and existing OpenCV algorithms specifically relevant to your problem. And some of the most interesting research actually comes from automotive suppliers—not generic image-quality research.

My key finding is that you should investigate three different classes of technology:

1. Dedicated camera-fault detection: models designed to identify dirt, mud, water droplets, occlusion, and other sensor degradation.
2. Image-quality assessment: algorithms and AI models that detect or quantify blur, exposure problems, and degraded visual quality.
3. Temporal and pipeline diagnostics: OpenCV and video-processing techniques for frame freezes, stale images, dropped frames, and processing latency.

The third category is particularly important: an AI image classifier cannot reliably tell whether a perfectly clear image arrived 500 milliseconds late. That requires timestamps and pipeline instrumentation.

## 1. The most relevant discovery: Models developed for automotive camera soiling

[Let's Get Dirty: GAN Based Data Augmentation for Camera Lens Soiling Detection in Autonomous Driving · Issue #336 · tkuri/papers · GitHub](https://images.openai.com/static-rsc-4/j-UiVOgZiDDkhuEUNL7CSyJl3MR0G-hvpUTJ27gjscfdJrvK9Q890p4DufPjEBnn1PHMX6K-FFla0DbkFXNZUUA4Pz5hJlh_3QfvED4e65k1Mc2VHE3YGGjhIWCbahoxhiC-syzlmoS4sXiRlb1hWnVQU7zTPCB9SHddxgX0bD0?purpose=inline)

SoildNet

An automotive-focused deep CNN designed to recognize lens contamination at the image-tile level. Its paper describes compression techniques for low-power embedded processors, reporting 9.72% of the baseline network's trainable parameters and a model size reduced by more than sevenfold.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://arxiv.org\&sz=32)

arxiv.org



Promising architecture, but I have not verified an official ready-to-run pretrained checkpoint.

[Review — SoilingNet: Soiling Detection on Automotive Surround-View Cameras | by Sik-Ho Tsang | Medium](https://images.openai.com/static-rsc-4/faTwkpYeW1WJX9Pg5SQssd-o8KyKHmD9pIzrwZyxhZCfQYnSo12ULznqllJUldSXvQehblHoq6qbbw0LAfy0qLUfssd7OBC7yH-XfEgRz9-UpBqiAzM-SnmYPD8L-oEUIBDsxG-oNqLmKBhUImWzPHPu4e0b7l5Es9w4FeBe6aI?purpose=inline)

SoilingNet

Designed around identifying opaque and transparent contaminants on automotive cameras, using a CNN-based approach. This is closer to actual ADAS health monitoring than a standard object detector.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://arxiv.org\&sz=32)

arxiv.org



Published research; a verified official pretrained deployment package is not established.

These are important leads, but there's a distinction worth keeping throughout the research: a published AI architecture is not necessarily a downloadable, working model. Below I'll distinguish ready-to-use software from implementations requiring training or engineering.

## 2. An ADAS soiling project with downloadable trained models

WoodScape Revision — Beránek et al., 2025

Trained models published

Research: Soiling Detection for Advanced Driver Assistance Systems

This is one of the strongest candidates I found for your project. It treats dirt detection as semantic segmentation, identifying which image regions are clear, transparent, semi-transparent, or opaque—not just whether the entire frame is good or bad.

[Review — Ensemble-based Semi-supervised Learning to Improve Noisy Soiling Annotations in Autonomous Driving | by Sik-Ho Tsang | Medium](https://images.openai.com/static-rsc-4/HyhWlUlF5igkTq4M1o3KvBprnQsJ2zmA_-ptq9KfkD9qoYt-8fpMTMhRullISoMwFsdnkhCszFzodhQn_4Rft3AoJ4mEO1DLRxehrRYodZae445rLsX7xA3q7O-wtKeKlvImjxvuTiDuPtp1CyV4QL6x0BctJ9cnun1Q-rd1tYU?purpose=inline)

Code

[GitHub repository](https://github.com/filipberanek/woodscape_revision)

Trained weights

[Authors' model archive](https://drive.google.com/file/d/13k17SjgQHZCO-1Ctr3DY_bW6DGvQZZie/view)

The authors compare segmentation networks using a ResNet-18 encoder as a baseline. Their repository includes training, prediction and evaluation scripts, plus a link to the trained models and their outputs.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://arxiv.org\&sz=32)

arxiv.org

+1



Why this is particularly relevant:

- It can localize contamination rather than only raising a global alarm.
- It uses automotive camera images from WoodScape.
- You can experiment with actual trained checkpoints rather than starting from random weights.
- The research specifically addresses mislabeled examples and train/test data leakage in the original WoodScape split—an important issue when evaluating accuracy.&#x20;

  [image](https://www.google.com/s2/favicons?domain=https://arxiv.org\&sz=32)

  arxiv.org



Limitations: It requires PyTorch integration and benchmarking. It is not a proven plug-and-play 30 FPS CPU detector. I also couldn't establish an explicit permissive license in the repository, so the code, weights and underlying dataset need separate license verification before commercial use.

## 3. More open-source models and implementations worth testing

I found several additional projects with different levels of readiness.

| Project                                                                                                            | Detects                                                        | Downloadable model?                                  | Offline suitability                         | My assessment                                            |
| ------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------- | ---------------------------------------------------- | ------------------------------------------- | -------------------------------------------------------- |
| [Raindrop Detection CNN](https://github.com/tobybreckon/raindrop-detection-cnn)                                    | Water droplets and their locations                             | Yes, pretrained TensorFlow weights                   | CPU possible, modern port needed            | Excellent specialized experiment                         |
| [Deep Blur Detection and Classification](https://github.com/HyeongseokSon1/deep_blur_detection_and_classification) | Motion blur versus defocus blur, with spatial maps             | Yes, downloadable weights                            | Legacy TensorFlow 1.x                       | Excellent comparison research, poor immediate deployment |
| [LBP Defocus Segmentation](https://github.com/xinario/defocus_segmentation)                                        | Localized loss of focus                                        | No neural weights required                           | CPU-friendly sharpness component            | Strong classical alternative                             |
| [CaUS Visibility Artifacts](https://github.com/vd-kuznetsov/CaUS_Visibility_Artifacts)                             | Visibility artifacts including soiling and adverse conditions  | Training notebooks; pretrained weights not confirmed | Requires adaptation                         | Useful for building a custom classifier                  |
| [Anomalib — EfficientAD](https://github.com/open-edge-platform/anomalib)                                           | Learned visual anomalies, potentially persistent contamination | Requires task-specific training                      | CPU deployment possible                     | Interesting experimental detector                        |
| [Lens Smear Detection](https://github.com/nikitbobba/lens-smear-detection)                                         | Lens-fixed smear patterns across multiple images               | No AI model                                          | Classical OpenCV, Python 2.7 implementation | Valuable algorithmic idea, not drop-in modern software   |

The raindrop project is particularly concrete: its repository includes a `download-models.sh` script and pretrained weights for a downscaled AlexNet-based detector. The reference implementation uses TensorFlow 1.9 and OpenCV 3.3.1, so it needs modernization and benchmarking before integrating into your three-stream system.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub

+5



### Another useful dataset for your project

[RaindropsOnWindshield](https://github.com/Evocargo/RaindropsOnWindshield) provides 8,190 images, including 3,390 with raindrops, with polygon annotations and binary masks. It also includes a synthetic raindrop generator. Unlike a generic rain dataset, it focuses on drops adhering to the camera or windshield. The project states a CC BY 4.0 license.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub

+1



This could directly improve your simulated fault injection: add physically plausible, stationary-on-lens raindrop masks rather than only applying global Gaussian blur or darkening.

## 4. What OpenCV itself can detect without deep learning

This is the part I would prioritize for raw speed.

OpenCV already contains fast, native C++ implementations of image-processing algorithms. Python calls these optimized routines, so using OpenCV from Python does not necessarily mean the pixel processing itself is slow.

| Fault                 | OpenCV / other algorithm                                | How reliable is the signal?                                  | Relative compute cost |
| --------------------- | ------------------------------------------------------- | ------------------------------------------------------------ | --------------------- |
| Global image blur     | Variance of Laplacian                                   | Useful baseline, scene-dependent                             | Very low              |
| Localized blur        | Grid-based Laplacian / Tenengrad / LBP sharpness        | Better localization; still affected by texture               | Low                   |
| Motion blur           | Directional gradients, FFT analysis                     | Can detect blur characteristics; ambiguous with scene motion | Low–medium            |
| Image too dark        | Luminance histogram, shadow clipping                    | Strong measurement; not necessarily a camera fault           | Very low              |
| Overexposure / glare  | Saturation, highlight clipping, regional analysis       | Good at locating blown-out regions                           | Very low              |
| Blackout              | Mean brightness, histogram, low entropy                 | Strong signal for all-black frames                           | Very low              |
| Frozen frames         | Frame difference, hashes, SSIM                          | Needs timestamps and scene-motion context                    | Very low–low          |
| Camera delay          | Source/arrival timestamps and queue age                 | Direct measurement when timestamps are trustworthy           | Negligible            |
| Dropped frames        | Frame sequence IDs and timestamp gaps                   | Direct measurement when source metadata is available         | Negligible            |
| Rain/dirt/obstruction | Persistent regional artifacts, optical-flow consistency | Suspicion only; specialized models are stronger              | Low–medium            |
| Fog / low visibility  | Local contrast and edge attenuation                     | Difficult to distinguish from legitimate scene content       | Low                   |
| Compression artifacts | Blocking/edge artifact metrics                          | Detects certain kinds of video degradation                   | Low–medium            |

These are relative engineering estimates, not measured benchmarks on your computer.

OpenCV also has a dedicated no-reference image-quality implementation, BRISQUE, which uses statistical image features and a trained SVM. A lower BRISQUE score generally means better image quality.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://docs.opencv.org\&sz=32)

OpenCV Documentation

+1



For temporal problems, FFmpeg provides `freezedetect`, `blackdetect`, `blurdetect`, and `blockdetect` filters. These are already implemented and useful for comparing your detector against an independent baseline.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.ffmpeg.org\&sz=32)

FFmpeg

+1



## 5. Ready-to-use image quality models, compared

Not every model here should run in the continuous safety loop. Some are better suited to periodic checks or offline evaluation.

| Model / implementation                                                                           | Type                              | Ready to test                         | Expected CPU suitability          | Best role                            |
| ------------------------------------------------------------------------------------------------ | --------------------------------- | ------------------------------------- | --------------------------------- | ------------------------------------ |
| [OpenCV BRISQUE](https://docs.opencv.org/4.6.0/d8/d99/classcv_1_1quality_1_1QualityBRISQUE.html) | Statistical features + SVM        | Yes, with model files                 | Good candidate                    | Periodic image quality               |
| [Python BRISQUE](https://github.com/rehanguha/brisque)                                           | Statistical features + SVM        | Yes                                   | Good candidate                    | Simple local quality scoring         |
| [NIQE via PyIQA](https://github.com/chaofengc/IQA-PyTorch)                                       | Natural-scene statistics          | Yes                                   | Benchmark first                   | No-reference image quality           |
| [CNNIQA via PyIQA](https://github.com/chaofengc/IQA-PyTorch)                                     | Compact learned IQA model         | Yes, library weights                  | Worth benchmarking                | Lightweight learned quality baseline |
| [TOPIQ-NR](https://github.com/chaofengc/IQA-PyTorch)                                             | Deep learned image-quality model  | Yes, pretrained implementation        | More demanding                    | Secondary quality assessment         |
| [MUSIQ](https://github.com/chaofengc/IQA-PyTorch)                                                | Transformer-based IQA             | Yes, pretrained implementation        | More demanding                    | Research comparison                  |
| [MobileIQA](https://github.com/chencn2020/MobileIQA)                                             | Distilled lightweight IQA network | Code available; checkpoint not listed | Designed for efficient use        | Research / further training          |
| [FAST-VQA-M](https://github.com/puwang40/FAST-VQA)                                               | Learned video quality assessment  | Yes, pretrained weights               | Not my first CPU real-time choice | Offline video-quality evaluation     |

The PyIQA library includes downloadable pretrained models and published CPU/GPU efficiency benchmarking facilities. Some models require weight downloads on first use. MobileIQA is particularly relevant architecturally, but its repository's checklist still leaves its checkpoint unpublished.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub

+3



Important: An image-quality score is not an ADAS safety probability. A beautiful, sharp image can still be unsafe because a critical road region is blocked.

## 6. My recommended architecture for your existing project

I would use a hybrid system with three processing levels.

Your three recorded camera streams

Timestamp-paced simulated feeds

Level 1 — Every frame

CPU

Timestamp age, missing/dropped frames, queue delay, blackout, exposure, thumbnail sharpness, frame differences.

Fast checks that must not depend on the AI model

Level 2 — Scheduled / suspicious frames

BRISQUE or NIQE for general quality, local blur maps, temporal regional consistency.

Frequency chosen from measured latency and fault-detection requirements

Level 3 — Specialized model

WoodScape soiling segmentation or trained raindrop detection, where dirt or occlusion is suspected.

Localized masks and stronger fault-specific evidence

Evidence fusion and event state

Fault suspected · Confirmed by simulation · Unknown / insufficient evidence

Your existing dashboard

Separate pipeline faults, image quality, regional masks and detection latency

One important design requirement: don't only invoke Level 3 after a cheap detector fires. That creates blind spots when the cheap detector misses an unfamiliar fault. Run occasional independent model checks as well.

### Which techniques work best for each fault?

| Fault scenario       | Primary detector                            | Secondary detector                                  |
| -------------------- | ------------------------------------------- | --------------------------------------------------- |
| Entire frame blurry  | Laplacian + Tenengrad                       | CNNIQA / BRISQUE                                    |
| Localized dirty lens | WoodScape segmentation                      | Persistent regional texture/flow anomaly            |
| Water droplets       | Raindrop CNN                                | Temporal and local-gradient consistency             |
| Frozen image         | Timestamps, frame IDs, frame differences    | Optical flow with motion context                    |
| Processing lag       | Monotonic capture-to-processing age         | Queue depth and delivery intervals                  |
| Blackout             | Histogram / near-black pixel ratio          | Delivery and decoder state                          |
| Severe glare         | Highlight clipping and affected-region size | BRISQUE / visibility assessment                     |
| Fog or low contrast  | Local contrast and gradient statistics      | Quality-model score / downstream perception testing |

I would not use a generic object-detection model like YOLO as the primary detector for lens dirt or pipeline lag. A specialized segmentation model is better aligned with dirt, while timestamps are necessary for lag.

## 7. You can start testing immediately

### A. OpenCV blur and exposure measurements

```
import cv2import numpy as npdef image_metrics(frame):    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)    small = cv2.resize(gray, (320, 180))    laplacian = cv2.Laplacian(small, cv2.CV_64F)    return {        "sharpness": float(laplacian.var()),        "mean_brightness": float(small.mean()),        "dark_fraction": float(np.mean(small < 20)),        "clipped_bright_fraction": float(np.mean(small > 245)),    }
```

This is a measurement baseline, not a validated fault classifier. Sharpness thresholds need calibration per resolution, camera, lighting condition and scene characteristics.

### B. OpenCV BRISQUE (with pretrained model)

Install the contrib build:

```
pip install opencv-contrib-python
```

Download the two official sample model files:

[BRISQUE model](https://github.com/opencv/opencv_contrib/blob/4.x/modules/quality/samples/brisque_model_live.yml) and [feature normalization data](https://github.com/opencv/opencv_contrib/blob/4.x/modules/quality/samples/brisque_range_live.yml).

Then use:

```
import cv2brisque = cv2.quality.QualityBRISQUE_create(    "brisque_model_live.yml",    "brisque_range_live.yml")score = float(brisque.compute(frame)[0])print("BRISQUE:", score)
```

After installing dependencies and downloading those model files, inference runs locally. Don't mix multiple mutually conflicting OpenCV wheel variants in the same environment.

### C. FFmpeg freeze/blackout baseline

```
ffmpeg -hide_banner -i camera1.mp4 \
  -vf "freezedetect=n=-60dB:d=0.5,blackdetect=d=0.2" \
  -an -f null -
```

This detects stretches of unusually similar or black decoded video content. It does not prove that a real camera stopped working, and processing a recorded file faster than real time does not reproduce delivery lag.

For your simulated lag and drops, use your simulator's original source timestamps and measured delivery timestamps.

## 8. Accuracy and real-time performance: what you should actually benchmark

One useful published number is that the 2025 WoodScape Revision research reports 94.0% pixel classification accuracy for an FPNet segmentation configuration with a ResNet-18 encoder on its evaluated dataset. Increasing the encoder to ResNet-50 yielded 94.5% in that experiment.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://arxiv.org\&sz=32)

arXiv



That's useful evidence that a relatively modest backbone can be competitive. But it is not 94% real-world ADAS fault-detection reliability, and it doesn't establish inference speed on your computer.

I would use the following acceptance metrics.

| Measurement                      | Why it matters                                         |
| -------------------------------- | ------------------------------------------------------ |
| Recall per fault type            | Whether your detector misses dangerous degradation     |
| False alarms per camera-hour     | Whether ordinary road scenes cause constant warnings   |
| Detection latency, p95/p99       | Whether faults are recognized promptly                 |
| Per-class mask IoU               | Whether soiling localization is accurate               |
| End-to-end age of evidence       | Whether the dashboard is displaying stale findings     |
| CPU/GPU utilization and RAM      | Whether all three streams can run together             |
| Worst-case frame-processing time | Whether spikes cause queue buildup                     |
| Recovery time                    | Whether the monitor detects when the fault has cleared |

Test on clean moving roads, stationary traffic, tunnels, night scenes, rain, sun glare, trees, walls, and repetitive textures. Those are important hard negatives for blur and freeze detectors.

Also, because your three videos represent overlapping views rather than three independent cameras, their agreement is not proof of independent sensor reliability. You should benchmark per stream first.

## 9. Final shortlist: What I would adopt first

## 1

OpenCV classical metrics + timestamp monitoring

Best immediate foundation. Fast, offline, controllable, and directly suited to your existing implementation.

## 2

WoodScape Revision — lightweight segmentation configurations

My top choice to investigate for actual dirt/occlusion localization. Start with the ResNet-18/LinkNet or FPNet checkpoint configurations if present in the authors' archive.

## 3

OpenCV BRISQUE + NIQE comparison

Useful pretrained and statistical alternatives for quality assessment. Treat scores as supporting evidence, not final safety decisions.

## 4

Raindrop Detection CNN

A credible specialized pretrained experiment for water contamination. It will require legacy TensorFlow modernization.

## 5

EfficientAD / custom small CNN

Investigate after collecting sufficient real and simulated data. Particularly relevant if your existing models cannot generalize to your camera's specific faults.

For deployment, consider exporting a suitable trained CNN to ONNX and benchmarking ONNX Runtime on CPU, including INT8 quantization. ONNX Runtime recommends static quantization for CNNs but cautions that quantization doesn't always improve latency on older CPUs.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://onnxruntime.ai\&sz=32)

onnxruntime



My overall recommendation is to keep OpenCV + timestamps as the primary real-time monitor, and use specialized automotive soiling segmentation as the most interesting AI addition. This gives you the strongest combination of speed, diagnosability, and a meaningful technical contribution.

The remaining unknown is your actual computer specification. Your CPU, RAM, GPU, and input-video resolution/FPS will determine which neural networks can run concurrently without introducing the very latency your safety helper is supposed to detect.
