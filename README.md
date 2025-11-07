# 🧠 Automated Visual Inspection System

This project is a **comprehensive automated visual inspection system** designed for **industrial environments**.  
It leverages the power of **Python**, **OpenCV** for image processing, and a modern **CustomTkinter GUI** to provide a seamless real-time inspection experience.

---

## 🚀 Overview

The system captures real-time video from an **industrial camera** and automatically analyzes **manufactured parts** to detect potential **defects or irregularities**.

Its modular structure makes it adaptable to different camera models, production lines, and inspection standards.

### ✨ Key Features
- Real-time defect detection using **OpenCV**
- Interactive and responsive **CustomTkinter GUI**
- Integration with **Baumer industrial cameras**
- Adjustable **ROI (Region of Interest)** and **threshold settings**
- High performance with **multithreading** support
- Easy deployment as a **standalone executable (.exe)**

---

## 🖥️ System Architecture
```text
+-----------------------------+
|  Industrial Camera (Baumer) |
+-------------+---------------+
              |
              v
+-----------------------------+
|     Python + OpenCV Core    |
| (Image Capture & Processing)|
+-------------+---------------+
              |
              v
+-----------------------------+
|     CustomTkinter GUI       |
| (Visualization & Control)   |
+-----------------------------+





