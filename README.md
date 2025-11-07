# real-time-defect-detection-BAUMERCAMS
This project is a comprehensive automated visual inspection system designed for industrial environments. Leveraging the power of Python, OpenCV for image processing, and a CustomTkinter GUI, the system captures real-time video from an industrial camera, analyzes manufactured parts for defects.

Prerequisites
First, ensure you have installed the Baumer GAPI SDKs. The application cannot establish a connection with the camera if these SDKs are not installed.

Camera Configuration
Your camera ID is physically written on the camera's label. If you cannot find it, you can learn the ID by connecting to the camera using the Baumer Camera Explorer application.

Important: The required camera ID is the one that starts with U3V, not the one labeled S/N.

Building an Executable:
If you wish to convert the script into a standalone executable file (.exe), you can check out the createExe.py

Additional Notes:
If you experience performance issues such as lagging or freezing, it is likely caused by the resolution settings or the window scaling logic. You can access and adjust these settings directly within the code.

Berkant Akıncı
Doğu Pres
