# real-time-defect-detection-BAUMERCAMS
This project is a comprehensive automated visual inspection system designed for industrial environments. Leveraging the power of Python, OpenCV for image processing, and a CustomTkinter GUI, the system captures real-time video from an industrial camera, analyzes manufactured parts for defects.

Prerequisites
First, ensure you have installed the Baumer GAPI SDKs. The application cannot establish a connection with the camera if these SDKs are not installed.

Camera Configuration
Your camera ID is physically written on the camera's label. If you cannot find it, you can learn the ID by connecting to the camera using the Baumer Camera Explorer application.

Important: The required camera ID is the one that starts with U3V, not the one labeled S/N.

Building an Executable
If you wish to convert the script into a standalone executable file (.exe), you can use PyInstaller with the following command:

python -m PyInstaller --noconsole --name "YourApplicationName" your_script_name.py

Warning: You must know that PyInstaller does not automatically bundle the required Baumer neoapi files (.dll, .cti). After the build is complete, you must manually copy these files into the neoapi folder located inside your output directory (dist/YourApplicationName/).

Additional Notes
If you experience performance issues such as lagging or freezing, it is likely caused by the resolution settings or the window scaling logic. You can access and adjust these settings directly within the code.

Berkant Akıncı
