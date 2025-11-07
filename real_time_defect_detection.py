## Berkant Akinci
## date : 07.11.2025

import customtkinter as ctk
import cv2
import neoapi
import serial
import time
import os
import json
import numpy as np
from PIL import Image, ImageTk
import threading

class VisionController:
    def __init__(self):
        self.camera = None
        self.arduino = None
        self.is_running = False
        self.is_camera_connected = False
        self.is_arduino_connected = False
        self.thread = None
        self.shutdown_event = threading.Event()
        
        self.settings_file = "settings.json"

        self.AREA_MIN = 1000
        self.AREA_MAX = 3000
        self.EXPECTED_COUNT = 17
        self.MAX_DISTANCE = 135
        self.RELAY_ON_DURATION = 5
        self.ROI = (0, 900, 2200, 1400)
        
        # Performance Optimization: Process and display images at this width.
        # This reduces CPU load significantly compared to processing the full-resolution image.
        # All calculations involving coordinates or areas are scaled accordingly.
        self.display_width = 1280

        self.relay_deactivation_time = 0
        self.is_relay_active = False
        self.previous_state_is_ok = False
        self.ok_part_counter = 0

        self.update_image_callback = None
        self.update_status_callback = None
        self.log_callback = None

        self.load_settings()

    def load_settings(self):
        try:
            with open(self.settings_file, 'r') as f:
                settings = json.load(f)
                self.AREA_MIN = settings.get('AREA_MIN', self.AREA_MIN)
                self.AREA_MAX = settings.get('AREA_MAX', self.AREA_MAX)
                self.EXPECTED_COUNT = settings.get('EXPECTED_COUNT', self.EXPECTED_COUNT)
                self.MAX_DISTANCE = settings.get('MAX_DISTANCE', self.MAX_DISTANCE)
                self.RELAY_ON_DURATION = settings.get('RELAY_ON_DURATION', self.RELAY_ON_DURATION)
                print(f"[INFO] Settings loaded from '{self.settings_file}'.")
        except FileNotFoundError:
            print(f"[INFO] Settings file not found. Using default settings.")
            self.save_settings()
        except json.JSONDecodeError:
            print(f"[ERROR] Settings file is corrupt. Using default settings.")

    def save_settings(self):
        settings = {
            'AREA_MIN': self.AREA_MIN,
            'AREA_MAX': self.AREA_MAX,
            'EXPECTED_COUNT': self.EXPECTED_COUNT,
            'MAX_DISTANCE': self.MAX_DISTANCE,
            'RELAY_ON_DURATION': self.RELAY_ON_DURATION
        }
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
            message = f"[✔] Settings saved to '{self.settings_file}'."
            if self.log_callback:
                self.log(message)
            else:
                print(message)
        except Exception as e:
            message = f"[!] Failed to save settings: {e}"
            if self.log_callback:
                self.log(message)
            else:
                print(message)

    def log(self, message):
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def connect_camera(self, serial_number='282500009698'): 
        # Important: The serial number '282500009698' is specific to one camera.
        # You must change this to match the serial number of your physical camera.
        # You can find this ID using the Baumer Camera Explorer software.
        try:
            self.camera = neoapi.Cam()
            self.camera.Connect(serial_number)
            try: self.camera.f.ExposureAuto.Set(neoapi.ExposureAuto_Off)
            except: pass
            try: self.camera.f.GainAuto.Set(neoapi.GainAuto_Off)
            except: pass
            try: self.camera.f.BalanceWhiteAuto.Set(neoapi.BalanceWhiteAuto_Off)
            except: pass
            self.camera.f.ExposureTime.Set(39000)
            self.camera.f.Gain.Set(0.0)
            try: self.camera.f.PixelFormat.Set(neoapi.PixelFormat_BGR8)
            except: self.camera.f.PixelFormat.Set(neoapi.PixelFormat_Mono8)
            self.camera.f.TriggerMode.value = neoapi.TriggerMode_Off
            self.is_camera_connected = True
            self.log("[✔] Camera connected and configured successfully.")
            return True
        except Exception as e:
            self.log(f"[!] Failed to connect to camera: {e}")
            self.is_camera_connected = False
            return False

    def connect_arduino(self, port='COM4', baudrate=115200):
        try:
            self.arduino = serial.Serial(port=port, baudrate=baudrate, timeout=.1)
            time.sleep(1)
            self.is_arduino_connected = True
            self.log(f"[✔] Connected to Arduino on port {port}.")
            return True
        except serial.SerialException as e:
            self.log(f"[!] Failed to connect to Arduino: {e}")
            self.is_arduino_connected = False
            return False
            
    def start_processing(self):
        self.is_running = True
        self.log("Processing started/resumed.")

    def stop_processing(self):
        self.is_running = False
        self.log("Processing paused.")

    def start_processing_thread(self):
        if not self.is_camera_connected:
            self.log("[!] Cannot start thread. Camera is not connected.")
            return
        self.thread = threading.Thread(target=self._processing_loop)
        self.thread.daemon = True
        self.thread.start()

    def _processing_loop(self):
        kernel_open = np.ones((4, 4), np.uint8)
        kernel_close = np.ones((8, 8), np.uint8)
        
        while not self.shutdown_event.is_set():
            if not self.is_running:
                time.sleep(0.1)
                continue

            try:
                img_object = self.camera.GetImage(1000)
                if img_object.IsEmpty(): continue

                frame_original = img_object.GetNPArray()
                
                # --- Resolution Handling and Scaling ---
                # To improve performance, we resize the original high-resolution camera image 
                # to a smaller width (`self.display_width`). All subsequent processing and 
                # displaying happens on this resized frame.
                original_h, original_w = frame_original.shape[:2]
                scale_factor = self.display_width / original_w
                new_height = int(original_h * scale_factor)
                frame = cv2.resize(frame_original, (self.display_width, new_height), interpolation=cv2.INTER_AREA)
                # The `scale_factor` is crucial for converting measurements (like area and distance) 
                # made on the resized image back to their original real-world scale.
                
                if len(frame.shape) == 2 or (len(frame.shape) == 3 and frame.shape[2] == 1):
                    frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                
                rx1, ry1, rx2, ry2 = self.ROI
                sx1, sy1, sx2, sy2 = int(rx1 * scale_factor), int(ry1 * scale_factor), int(rx2 * scale_factor), int(ry2 * scale_factor)
                
                if sx1 >= sx2 or sy1 >= sy2:
                    if self.update_image_callback: self.update_image_callback(frame);
                    continue

                roi = frame[sy1:sy2, sx1:sx2].copy()
                if roi.size == 0: continue

                gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
                mask = np.zeros((thresh.shape[0]+2, thresh.shape[1]+2), np.uint8)
                cv2.floodFill(thresh, mask, (0, 0), 0)
                clean = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel_open)
                filled = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, kernel_close)
                num_labels, _, stats, centroids = cv2.connectedComponentsWithStats(filled, connectivity=8)
                
                processed_roi_image = cv2.cvtColor(filled, cv2.COLOR_GRAY2BGR)
                components = []
                for j in range(1, num_labels):
                    x, y, w, h, area = stats[j]
                    if (area / (scale_factor**2)) < self.AREA_MIN: continue
                    components.append({'x': x, 'y': y, 'w': w, 'h': h, 'area': area, 
                                       'cx': int(centroids[j][0]), 'cy': int(centroids[j][1]),
                                       'is_area_faulty': (area / (scale_factor**2)) > self.AREA_MAX})
                components.sort(key=lambda p: p['cx'])

                errors, count_error_detail = self.detect_errors(components, scale_factor)
                self.draw_visuals(processed_roi_image, components, errors, scale_factor)
                self.control_relay_and_count(components, errors)
                
                frame[sy1:sy2, sx1:sx2] = processed_roi_image
                if self.update_image_callback: self.update_image_callback(frame)
                
                if self.update_status_callback:
                    remaining_time = max(0, self.relay_deactivation_time - time.time())
                    self.update_status_callback(
                        "ERROR" if errors else "OK", errors, count_error_detail,
                        self.is_relay_active, remaining_time,
                        self.ok_part_counter
                    )

                time.sleep(0.05)

            except Exception as e:
                self.log(f"Error in processing loop: {e}")
                time.sleep(1)

    def detect_errors(self, components, scale_factor):
        errors = []
        count_error_detail = ""
        actual_count = len(components)
        if actual_count != self.EXPECTED_COUNT:
            errors.append("Count Error")
            count_error_detail = f"({actual_count}/{self.EXPECTED_COUNT})"
        if len(components) > 1:
            distances = [int(np.hypot(components[j+1]['cx'] - p['cx'], components[j+1]['cy'] - p['cy'])) for j, p in enumerate(components[:-1])]
            if any((d / scale_factor) > self.MAX_DISTANCE for d in distances):
                errors.append("Distance Error")
        if any(p['is_area_faulty'] for p in components):
            errors.append("Area Error")
        return errors, count_error_detail
        
    def draw_visuals(self, image, components, errors, scale_factor):
        if len(components) > 1:
            for j in range(len(components) - 1):
                p1, p2 = components[j], components[j+1]
                distance_px = int(np.hypot(p2['cx'] - p1['cx'], p2['cy'] - p1['cy']))
                distance_original = int(distance_px / scale_factor)
                color = (0, 0, 255) if distance_original > self.MAX_DISTANCE else (0, 255, 0)
                cv2.line(image, (p1['cx'], p1['cy']), (p2['cx'], p2['cy']), color, 2)
        for idx, p in enumerate(components, start=1):
            color_box = (0, 0, 255) if p['is_area_faulty'] or errors else (0, 255, 0)
            cv2.rectangle(image, (p['x'], p['y']), (p['x'] + p['w'], p['y'] + p['h']), color_box, 2)
            cv2.putText(image, str(idx), (p['cx'] - 10, p['y'] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

    def control_relay_and_count(self, components, errors):
        current_time = time.time()
        current_state_is_ok = not errors

        if current_state_is_ok and not self.previous_state_is_ok and not self.is_relay_active:
            self.ok_part_counter += 1
            self.log(f"[COUNT] OK part detected. Total: {self.ok_part_counter}")

        if self.is_relay_active and current_time >= self.relay_deactivation_time:
            self.is_relay_active = False
            self.send_arduino_command('OFF')

        if not self.is_relay_active and current_state_is_ok and not self.previous_state_is_ok:
            self.is_relay_active = True
            self.relay_deactivation_time = current_time + self.RELAY_ON_DURATION
            self.send_arduino_command('ON')
        
        self.previous_state_is_ok = current_state_is_ok

    def send_arduino_command(self, command):
        if self.is_arduino_connected and self.arduino:
            try:
                self.arduino.write(bytes(command, 'utf-8'))
                self.log(f"[RELAY] -> Sent command: {command}.")
            except Exception as e:
                self.log(f"Could not send command to Arduino: {e}")

    def disconnect(self):
        self.shutdown_event.set()
        if self.thread: self.thread.join(timeout=1.5)
        self.log("Processing thread terminated safely.")
        if self.camera and self.is_camera_connected: self.camera.Disconnect(); self.log("Camera connection closed.")
        if self.arduino and self.is_arduino_connected: self.send_arduino_command('OFF'); self.arduino.close(); self.log("Arduino connection closed.")

class WelcomeScreen(ctk.CTk):
    def __init__(self, start_callback):
        super().__init__()
        self.start_callback = start_callback
        self.title("Welcome")
        self.geometry("450x200")
        self.after(100, lambda: self.eval('tk::PlaceWindow . center'))
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        welcome_label = ctk.CTkLabel(self, text="Visual Analysis and Quality Control System", font=ctk.CTkFont(size=20, weight="bold"))
        welcome_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.grid(row=1, column=0, padx=20, pady=20, sticky="ew")
        button_frame.grid_columnconfigure((0, 1), weight=1)
        start_button = ctk.CTkButton(button_frame, text="Start System", command=self.start_app, font=ctk.CTkFont(size=14, weight="bold"), height=40)
        start_button.grid(row=0, column=0, padx=10, sticky="ew")
        exit_button = ctk.CTkButton(button_frame, text="Exit", command=self.quit_app, font=ctk.CTkFont(size=14, weight="bold"), height=40, fg_color="#D9534F")
        exit_button.grid(row=0, column=1, padx=10, sticky="ew")

    def start_app(self):
        self.destroy()
        self.start_callback()

    def quit_app(self):
        self.destroy()

class App(ctk.CTk):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.is_closing = False
        self.settings_locked = True
        self.SETTINGS_PASSWORD = "Dp123456"

        self.title("Visual Analysis and Quality Control System")
        self.geometry("1600x900")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.grid_columnconfigure(0, weight=4)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.video_panel = ctk.CTkFrame(self)
        self.video_panel.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.video_panel.grid_rowconfigure(0, weight=1)
        self.video_panel.grid_columnconfigure(0, weight=1)

        self.video_label = ctk.CTkLabel(self.video_panel, text="Waiting for camera...")
        self.video_label.grid(row=0, column=0, sticky="nsew")

        self.control_panel = ctk.CTkFrame(self, width=400)
        self.control_panel.grid(row=0, column=1, padx=(0, 10), pady=10, sticky="nsew")
        self._create_control_widgets()

        self.controller.update_image_callback = self.schedule_video_update
        self.controller.update_status_callback = self.schedule_status_update
        self.controller.log_callback = self.log_message
        
        self._connect_devices()
        if self.controller.is_camera_connected: self.controller.start_processing_thread()

    def _create_control_widgets(self):
        panel = self.control_panel
        panel.grid_columnconfigure(0, weight=1)
        
        row = 0
        top_frame = ctk.CTkFrame(panel)
        top_frame.grid(row=row, column=0, padx=10, pady=10, sticky="ew")
        top_frame.grid_columnconfigure((0,1,2), weight=1)
        self.start_button = ctk.CTkButton(top_frame, text="Start", command=self.start_analysis, state="disabled")
        self.start_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.stop_button = ctk.CTkButton(top_frame, text="Pause", command=self.stop_analysis, state="disabled", fg_color="#D9534F")
        self.stop_button.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.exit_button = ctk.CTkButton(top_frame, text="Exit", command=self.on_closing, fg_color="#6C757D")
        self.exit_button.grid(row=0, column=2, padx=5, pady=5, sticky="ew")

        row += 1
        stats_frame = ctk.CTkFrame(panel)
        stats_frame.grid(row=row, column=0, padx=10, pady=5, sticky="ew")
        stats_frame.grid_columnconfigure(0, weight=1)
        self.ok_counter_label = ctk.CTkLabel(stats_frame, text="OK Part Counter: 0", font=ctk.CTkFont(size=18, weight="bold"), text_color="#5CB85C")
        self.ok_counter_label.pack(pady=10)

        row += 1
        status_frame = ctk.CTkFrame(panel)
        status_frame.grid(row=row, column=0, padx=10, pady=5, sticky="ew")
        status_frame.grid_columnconfigure(0, weight=1)
        self.overall_status_label = ctk.CTkLabel(status_frame, text="STATUS: WAITING", font=ctk.CTkFont(size=20, weight="bold"))
        self.overall_status_label.pack(pady=5)
        self.relay_status_label = ctk.CTkLabel(status_frame, text="Relay: INACTIVE", font=ctk.CTkFont(size=16))
        self.relay_status_label.pack(pady=5)
        self.error_list_label = ctk.CTkLabel(status_frame, text="Error Details:\n-", justify="left", anchor="n")
        self.error_list_label.pack(pady=5,padx=10, fill="x")
        
        row += 1
        settings_lock_frame = ctk.CTkFrame(panel)
        settings_lock_frame.grid(row=row, column=0, padx=10, pady=(10,0), sticky="ew")
        settings_lock_frame.grid_columnconfigure(0, weight=1)
        self.toggle_settings_button = ctk.CTkButton(settings_lock_frame, text="Unlock Settings", command=self.toggle_settings_lock)
        self.toggle_settings_button.pack(fill="x", padx=5, pady=5)
        
        row += 1
        self.params_frame = ctk.CTkFrame(panel)
        self.params_frame.grid_columnconfigure(1, weight=1)
        
        self.create_slider(self.params_frame, "Min Area", 0, 5000, self.controller.AREA_MIN, lambda v: setattr(self.controller, 'AREA_MIN', int(v)))
        self.create_slider(self.params_frame, "Max Area", 0, 5000, self.controller.AREA_MAX, lambda v: setattr(self.controller, 'AREA_MAX', int(v)))
        self.create_slider(self.params_frame, "Max Distance", 0, 500, self.controller.MAX_DISTANCE, lambda v: setattr(self.controller, 'MAX_DISTANCE', int(v)))
        self.create_slider(self.params_frame, "Relay Time (s)", 0, 60, self.controller.RELAY_ON_DURATION, lambda v: setattr(self.controller, 'RELAY_ON_DURATION', int(v)))
        
        expected_count_frame = ctk.CTkFrame(self.params_frame, fg_color="transparent")
        expected_count_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(expected_count_frame, text="Expected Count:").pack(side="left")
        self.expected_count_entry = ctk.CTkEntry(expected_count_frame, width=100)
        self.expected_count_entry.insert(0, str(self.controller.EXPECTED_COUNT))
        self.expected_count_entry.pack(side="right", fill="x", expand=True)
        self.expected_count_entry.bind("<KeyRelease>", self.update_expected_count)

        row += 1
        log_frame = ctk.CTkFrame(panel)
        log_frame.grid(row=row, column=0, padx=10, pady=10, sticky="nsew")
        panel.grid_rowconfigure(row, weight=1)
        self.log_box = ctk.CTkTextbox(log_frame, state="disabled", wrap="word")
        self.log_box.pack(expand=True, fill="both")

    def toggle_settings_lock(self):
        if self.settings_locked:
            dialog = ctk.CTkInputDialog(text="Enter password to unlock settings:", title="Password Required")
            password = dialog.get_input()
            if password == self.SETTINGS_PASSWORD:
                self.settings_locked = False
                self.params_frame.grid(row=4, column=0, padx=10, pady=0, sticky="ew")
                self.toggle_settings_button.configure(text="Lock Settings")
                self.log_message("[INFO] Settings panel unlocked.")
            elif password is not None:
                self.log_message("[ERROR] Incorrect password entered.")
        else:
            self.settings_locked = True
            self.params_frame.grid_remove()
            self.toggle_settings_button.configure(text="Unlock Settings")
            self.log_message("[INFO] Settings panel locked.")
    
    def create_slider(self, parent, text, from_, to, initial_val, command):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", expand=True, padx=10, pady=5)
        label = ctk.CTkLabel(frame, text=f"{text}: {initial_val}", width=120, anchor="w")
        label.pack(side="left")
        def slider_cmd(value):
            label.configure(text=f"{text}: {int(value)}")
            command(value)
            self.controller.save_settings() 
        slider = ctk.CTkSlider(frame, from_=from_, to=to, command=slider_cmd)
        slider.set(initial_val)
        slider.pack(side="left", fill="x", expand=True)

    def _connect_devices(self):
        cam_ok = self.controller.connect_camera()
        if cam_ok: self.start_button.configure(state="normal")
        self.controller.connect_arduino()

    def start_analysis(self):
        self.update_expected_count()
        self.controller.start_processing()
        self.start_button.configure(state="disabled", text="Start")
        self.stop_button.configure(state="normal")

    def stop_analysis(self):
        self.controller.stop_processing()
        self.start_button.configure(state="normal", text="Resume")
        self.stop_button.configure(state="disabled")
        self.overall_status_label.configure(text="STATUS: PAUSED", text_color="yellow")

    def update_expected_count(self, event=None):
        try:
            new_value = int(self.expected_count_entry.get())
            if self.controller.EXPECTED_COUNT != new_value:
                self.controller.EXPECTED_COUNT = new_value
                self.controller.save_settings()
        except (ValueError, TypeError):
            pass

    def schedule_video_update(self, cv2_image):
        if not self.is_closing:
            self.after(1, self.update_video_image, cv2_image)

    def schedule_status_update(self, *args):
        if not self.is_closing:
            self.after(1, self.update_status_info, *args)

    def update_video_image(self, cv2_image):
        try:
            if self.is_closing or not self.winfo_exists():
                return
            img = cv2.cvtColor(cv2_image, cv2.COLOR_BGR2RGB)
            img_pil = Image.fromarray(img)
            img_tk = ImageTk.PhotoImage(image=img_pil)
            self.video_label.img_tk = img_tk
            self.video_label.configure(image=img_tk, text="")
        except Exception: 
            pass

    def update_status_info(self, overall_status, errors, count_detail, relay_status, remaining_time, ok_counter):
        if self.is_closing or not self.winfo_exists():
            return
        self.ok_counter_label.configure(text=f"OK Part Counter: {ok_counter}")
        if not self.controller.is_running: return

        color = "#5CB85C" if overall_status == "OK" else "#D9534F"
        self.overall_status_label.configure(text=f"STATUS: {overall_status}", text_color=color)
        if relay_status: self.relay_status_label.configure(text=f"Relay: ACTIVE ({int(remaining_time)+1}s)", text_color="#5CB85C")
        else: self.relay_status_label.configure(text="Relay: INACTIVE", text_color="#D9534F")
        error_text = "Error Details:\n" + ("- None" if not errors else "\n".join([f"- {h}{count_detail if h=='Count Error' else ''}" for h in errors]))
        self.error_list_label.configure(text=error_text)

    def log_message(self, message):
        if self.is_closing or not self.winfo_exists():
            return
        self.log_box.configure(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def on_closing(self):
        if self.is_closing:
            return
        self.is_closing = True
        self.log_message("Closing application...")
        self.controller.disconnect()
        self.destroy()

if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    
    def launch_main_app():
        vision_controller = VisionController()
        app = App(vision_controller)
        app.mainloop()

    welcome_screen = WelcomeScreen(start_callback=launch_main_app)

    welcome_screen.mainloop()
