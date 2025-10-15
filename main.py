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

        # Analiz Parametreleri (Varsayılan Değerler)
        self.ALAN_MIN = 1000
        self.ALAN_MAX = 3000
        self.BEKLENEN_SAYI = 17
        self.MESAFE_MAX = 135
        self.ROLE_ACIK_KALMA_SURESI = 5
        self.ROI = (0, 900, 2200, 1400) # Orijinal yüksek çözünürlükteki koordinatlar
        
        # Optimizasyon Parametresi
        self.display_width = 1280 # Görüntünün işleneceği ve gösterileceği genişlik

        # Durum ve İstatistik Değişkenleri
        self.role_kapanma_zamani = 0
        self.role_aktif = False
        self.onceki_durum_hatasiz_miydi = False
        self.hatasiz_parca_sayaci = 0

        self.update_image_callback = None
        self.update_status_callback = None
        self.log_callback = None

        self.load_settings()

    def load_settings(self):
        """Ayarlari settings.json dosyasindan yükle."""
        try:
            with open(self.settings_file, 'r') as f:
                settings = json.load(f)
                self.ALAN_MIN = settings.get('ALAN_MIN', self.ALAN_MIN)
                self.ALAN_MAX = settings.get('ALAN_MAX', self.ALAN_MAX)
                self.BEKLENEN_SAYI = settings.get('BEKLENEN_SAYI', self.BEKLENEN_SAYI)
                self.MESAFE_MAX = settings.get('MESAFE_MAX', self.MESAFE_MAX)
                self.ROLE_ACIK_KALMA_SURESI = settings.get('ROLE_ACIK_KALMA_SURESI', self.ROLE_ACIK_KALMA_SURESI)
                # Loglama henüz başlamamış olabilir, bu yüzden print kullanıyoruz.
                print(f"[BİLGİ] Ayarlar '{self.settings_file}' dosyasindan yüklendi.")
        except FileNotFoundError:
            print(f"[BİLGİ] Ayar dosyasi bulunamadi. Varsayilan ayarlar kullanilacak.")
            self.save_settings() # İlk çalıştırmada varsayılan ayarlarla dosya oluştur
        except json.JSONDecodeError:
            print(f"[HATA] Ayar dosyasi bozuk. Varsayilan ayarlar kullanilacak.")

    def save_settings(self):
        """Mevcut ayarlari settings.json dosyasina kaydeder."""
        settings = {
            'ALAN_MIN': self.ALAN_MIN,
            'ALAN_MAX': self.ALAN_MAX,
            'BEKLENEN_SAYI': self.BEKLENEN_SAYI,
            'MESAFE_MAX': self.MESAFE_MAX,
            'ROLE_ACIK_KALMA_SURESI': self.ROLE_ACIK_KALMA_SURESI
        }
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
            # Log callback hazırsa kullan, değilse print et
            message = f"[✔] Ayarlar '{self.settings_file}' dosyasina kaydedildi."
            if self.log_callback:
                self.log(message)
            else:
                print(message)
        except Exception as e:
            message = f"[!] Ayarlar kaydedilemedi: {e}"
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
            self.log("[✔] Kamera başariyla bağlandi ve ayarlandi.")
            return True
        except Exception as e:
            self.log(f"[!] Kamera bağlanamadi: {e}")
            self.is_camera_connected = False
            return False

    def connect_arduino(self, port='COM4', baudrate=115200):
        try:
            self.arduino = serial.Serial(port=port, baudrate=baudrate, timeout=.1)
            time.sleep(1)
            self.is_arduino_connected = True
            self.log(f"[✔] Arduino'ya {port} portu üzerinden bağlanıldı.")
            return True
        except serial.SerialException as e:
            self.log(f"[!] Arduino'ya bağlanılamadı: {e}")
            self.is_arduino_connected = False
            return False
            
    def start_processing(self):
        self.is_running = True
        self.log("Analiz başlatıldı/devam ediyor.")

    def stop_processing(self):
        self.is_running = False
        self.log("Analiz duraklatıldı.")

    def start_processing_thread(self):
        if not self.is_camera_connected:
            self.log("[!] Thread başlatılamadı. Kamera bağlı değil.")
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
                
                h, w = frame_original.shape[:2]
                scale_factor = self.display_width / w
                new_height = int(h * scale_factor)
                frame = cv2.resize(frame_original, (self.display_width, new_height), interpolation=cv2.INTER_AREA)

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
                
                resim_doldur = cv2.cvtColor(filled, cv2.COLOR_GRAY2BGR)
                parcalar = []
                for j in range(1, num_labels):
                    x, y, w, h, area = stats[j]
                    if (area / (scale_factor**2)) < self.ALAN_MIN: continue
                    parcalar.append({'x': x, 'y': y, 'w': w, 'h': h, 'area': area, 
                                     'cx': int(centroids[j][0]), 'cy': int(centroids[j][1]),
                                     'alan_hatali': (area / (scale_factor**2)) > self.ALAN_MAX})
                parcalar.sort(key=lambda p: p['cx'])

                hatalar, sayim_hatasi_detay = self.detect_errors(parcalar, scale_factor)
                self.draw_visuals(resim_doldur, parcalar, hatalar, scale_factor)
                self.control_relay_and_count(parcalar, hatalar)
                
                frame[sy1:sy2, sx1:sx2] = resim_doldur
                if self.update_image_callback: self.update_image_callback(frame)
                
                if self.update_status_callback:
                    kalan_sure = max(0, self.role_kapanma_zamani - time.time())
                    self.update_status_callback(
                        "HATALI" if hatalar else "HATASIZ", hatalar, sayim_hatasi_detay,
                        self.role_aktif, kalan_sure,
                        self.hatasiz_parca_sayaci
                    )

                time.sleep(0.05)

            except Exception as e:
                self.log(f"İşlem döngüsünde hata: {e}")
                time.sleep(1)

    def detect_errors(self, parcalar, scale_factor):
        hatalar = []
        sayim_hatasi_detay = ""
        gercek_sayi = len(parcalar)
        if gercek_sayi != self.BEKLENEN_SAYI:
            hatalar.append("Sayim Hatasi")
            sayim_hatasi_detay = f"({gercek_sayi}/{self.BEKLENEN_SAYI})"
        if len(parcalar) > 1:
            mesafeler = [int(np.hypot(parcalar[j+1]['cx'] - p['cx'], parcalar[j+1]['cy'] - p['cy'])) for j, p in enumerate(parcalar[:-1])]
            if any((d / scale_factor) > self.MESAFE_MAX for d in mesafeler):
                hatalar.append("Mesafe Hatasi")
        if any(p['alan_hatali'] for p in parcalar):
            hatalar.append("Alan Hatasi")
        return hatalar, sayim_hatasi_detay
        
    def draw_visuals(self, image, parcalar, hatalar, scale_factor):
        if len(parcalar) > 1:
            for j in range(len(parcalar) - 1):
                p1, p2 = parcalar[j], parcalar[j+1]
                mesafe_px = int(np.hypot(p2['cx'] - p1['cx'], p2['cy'] - p1['cy']))
                mesafe_orig = int(mesafe_px / scale_factor)
                renk = (0, 0, 255) if mesafe_orig > self.MESAFE_MAX else (0, 255, 0)
                cv2.line(image, (p1['cx'], p1['cy']), (p2['cx'], p2['cy']), renk, 2)
        for idx, p in enumerate(parcalar, start=1):
            color_box = (0, 0, 255) if p['alan_hatali'] or hatalar else (0, 255, 0)
            cv2.rectangle(image, (p['x'], p['y']), (p['x'] + p['w'], p['y'] + p['h']), color_box, 2)
            cv2.putText(image, str(idx), (p['cx'] - 10, p['y'] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

    def control_relay_and_count(self, parcalar, hatalar):
        simdi = time.time()
        mevcut_durum_hatasiz = not hatalar

        # Sadece "hatalı" bir durumdan "hatasız" bir duruma geçildiğinde VE röle pasif durumdayken say.
        if mevcut_durum_hatasiz and not self.onceki_durum_hatasiz_miydi and not self.role_aktif:
            self.hatasiz_parca_sayaci += 1
            self.log(f"[SAYIM] Hatasız parça algılandı. Toplam: {self.hatasiz_parca_sayaci}")

        # Rölenin açık kalma süresi dolduysa KAPAT.
        if self.role_aktif and simdi >= self.role_kapanma_zamani:
            self.role_aktif = False
            self.send_arduino_command('OFF')

        # Yeni bir "HATASIZ" olayı algılandıysa (HATALI'dan -> HATASIZ'a geçiş) röleyi AÇ.
        if not self.role_aktif and mevcut_durum_hatasiz and not self.onceki_durum_hatasiz_miydi:
            self.role_aktif = True
            self.role_kapanma_zamani = simdi + self.ROLE_ACIK_KALMA_SURESI
            self.send_arduino_command('ON')
        
        self.onceki_durum_hatasiz_miydi = mevcut_durum_hatasiz

    def send_arduino_command(self, command):
        if self.is_arduino_connected and self.arduino:
            try:
                self.arduino.write(bytes(command, 'utf-8'))
                self.log(f"[RÖLE] -> {command} komutu gönderildi.")
            except Exception as e:
                self.log(f"Arduino'ya komut gönderilemedi: {e}")

    def disconnect(self):
        self.shutdown_event.set()
        if self.thread: self.thread.join(timeout=1.5)
        self.log("Analiz thread'i güvenle sonlandirildi.")
        if self.camera and self.is_camera_connected: self.camera.Disconnect(); self.log("Kamera bağlantısı kesildi.")
        if self.arduino and self.is_arduino_connected: self.send_arduino_command('OFF'); self.arduino.close(); self.log("Arduino bağlantısı kesildi.")

class WelcomeScreen(ctk.CTk):
    def __init__(self, start_callback):
        super().__init__()
        self.start_callback = start_callback
        self.title("Hoş Geldiniz")
        self.geometry("450x200")
        self.after(100, lambda: self.eval('tk::PlaceWindow . center'))
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        welcome_label = ctk.CTkLabel(self, text="Görsel Analiz ve Kalite Kontrol Sistemi", font=ctk.CTkFont(size=20, weight="bold"))
        welcome_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.grid(row=1, column=0, padx=20, pady=20, sticky="ew")
        button_frame.grid_columnconfigure((0, 1), weight=1)
        start_button = ctk.CTkButton(button_frame, text="Sistemi Başlat", command=self.start_app, font=ctk.CTkFont(size=14, weight="bold"), height=40)
        start_button.grid(row=0, column=0, padx=10, sticky="ew")
        exit_button = ctk.CTkButton(button_frame, text="Çikis", command=self.quit_app, font=ctk.CTkFont(size=14, weight="bold"), height=40, fg_color="#D9534F")
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

        self.title("Görsel Analiz ve Kalite Kontrol Sistemi")
        self.geometry("1600x900")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.grid_columnconfigure(0, weight=4)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.video_panel = ctk.CTkFrame(self)
        self.video_panel.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.video_panel.grid_rowconfigure(0, weight=1)
        self.video_panel.grid_columnconfigure(0, weight=1)

        self.video_label = ctk.CTkLabel(self.video_panel, text="Kamera bekleniyor...")
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
        self.start_button = ctk.CTkButton(top_frame, text="Başlat", command=self.start_analysis, state="disabled")
        self.start_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.stop_button = ctk.CTkButton(top_frame, text="Duraklat", command=self.stop_analysis, state="disabled", fg_color="#D9534F")
        self.stop_button.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.exit_button = ctk.CTkButton(top_frame, text="Çıkış", command=self.on_closing, fg_color="#6C757D")
        self.exit_button.grid(row=0, column=2, padx=5, pady=5, sticky="ew")

        row += 1
        stats_frame = ctk.CTkFrame(panel)
        stats_frame.grid(row=row, column=0, padx=10, pady=5, sticky="ew")
        stats_frame.grid_columnconfigure(0, weight=1)
        self.hatasiz_sayac_label = ctk.CTkLabel(stats_frame, text="Hatasız Parça Sayacı: 0", font=ctk.CTkFont(size=18, weight="bold"), text_color="#5CB85C")
        self.hatasiz_sayac_label.pack(pady=10)

        row += 1
        status_frame = ctk.CTkFrame(panel)
        status_frame.grid(row=row, column=0, padx=10, pady=5, sticky="ew")
        status_frame.grid_columnconfigure(0, weight=1)
        self.genel_durum_label = ctk.CTkLabel(status_frame, text="DURUM: BEKLENİYOR", font=ctk.CTkFont(size=20, weight="bold"))
        self.genel_durum_label.pack(pady=5)
        self.role_durum_label = ctk.CTkLabel(status_frame, text="Röle: PASİF", font=ctk.CTkFont(size=16))
        self.role_durum_label.pack(pady=5)
        self.hata_list_label = ctk.CTkLabel(status_frame, text="Hata Detayları:\n-", justify="left", anchor="n")
        self.hata_list_label.pack(pady=5,padx=10, fill="x")
        
        row += 1
        settings_lock_frame = ctk.CTkFrame(panel)
        settings_lock_frame.grid(row=row, column=0, padx=10, pady=(10,0), sticky="ew")
        settings_lock_frame.grid_columnconfigure(0, weight=1)
        self.toggle_settings_button = ctk.CTkButton(settings_lock_frame, text="Ayarları Aç", command=self.toggle_settings_lock)
        self.toggle_settings_button.pack(fill="x", padx=5, pady=5)
        
        row += 1
        self.params_frame = ctk.CTkFrame(panel)
        self.params_frame.grid_columnconfigure(1, weight=1)
        
        self.create_slider(self.params_frame, "Min Alan", 0, 5000, self.controller.ALAN_MIN, lambda v: setattr(self.controller, 'ALAN_MIN', int(v)))
        self.create_slider(self.params_frame, "Max Alan", 0, 5000, self.controller.ALAN_MAX, lambda v: setattr(self.controller, 'ALAN_MAX', int(v)))
        self.create_slider(self.params_frame, "Max Mesafe", 0, 500, self.controller.MESAFE_MAX, lambda v: setattr(self.controller, 'MESAFE_MAX', int(v)))
        self.create_slider(self.params_frame, "Röle Süresi", 0, 60, self.controller.ROLE_ACIK_KALMA_SURESI, lambda v: setattr(self.controller, 'ROLE_ACIK_KALMA_SURESI', int(v)))
        
        beklenen_sayi_frame = ctk.CTkFrame(self.params_frame, fg_color="transparent")
        beklenen_sayi_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(beklenen_sayi_frame, text="Beklenen Sayı:").pack(side="left")
        self.beklenen_sayi_entry = ctk.CTkEntry(beklenen_sayi_frame, width=100)
        self.beklenen_sayi_entry.insert(0, str(self.controller.BEKLENEN_SAYI))
        self.beklenen_sayi_entry.pack(side="right", fill="x", expand=True)
        self.beklenen_sayi_entry.bind("<KeyRelease>", self.update_beklenen_sayi)

        row += 1
        log_frame = ctk.CTkFrame(panel)
        log_frame.grid(row=row, column=0, padx=10, pady=10, sticky="nsew")
        panel.grid_rowconfigure(row, weight=1)
        self.log_box = ctk.CTkTextbox(log_frame, state="disabled", wrap="word")
        self.log_box.pack(expand=True, fill="both")

    def toggle_settings_lock(self):
        if self.settings_locked:
            dialog = ctk.CTkInputDialog(text="Ayarları açmak için şifreyi girin:", title="Şifre Gerekli")
            password = dialog.get_input()
            if password == self.SETTINGS_PASSWORD:
                self.settings_locked = False
                self.params_frame.grid(row=4, column=0, padx=10, pady=0, sticky="ew")
                self.toggle_settings_button.configure(text="Ayarları Kilitle")
                self.log_message("[BİLGİ] Ayarlar paneli açıldı.")
            elif password is not None:
                self.log_message("[HATA] Yanliş şifre girildi.")
        else:
            self.settings_locked = True
            self.params_frame.grid_remove()
            self.toggle_settings_button.configure(text="Ayarları Aç")
            self.log_message("[BİLGİ] Ayarlar paneli kilitlendi.")
    
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
        self.update_beklenen_sayi()
        self.controller.start_processing()
        self.start_button.configure(state="disabled", text="Başlat")
        self.stop_button.configure(state="normal")

    def stop_analysis(self):
        self.controller.stop_processing()
        self.start_button.configure(state="normal", text="Devam Et")
        self.stop_button.configure(state="disabled")
        self.genel_durum_label.configure(text="DURUM: DURAKLATILDI", text_color="yellow")

    def update_beklenen_sayi(self, event=None):
        try:
            yeni_deger = int(self.beklenen_sayi_entry.get())
            if self.controller.BEKLENEN_SAYI != yeni_deger:
                self.controller.BEKLENEN_SAYI = yeni_deger
                self.controller.save_settings() # Değişiklik anında ayarları kaydet
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

    def update_status_info(self, genel_durum, hatalar, sayim_detay, role_durumu, kalan_sure, hatasiz_sayaci):
        if self.is_closing or not self.winfo_exists():
            return
        self.hatasiz_sayac_label.configure(text=f"Hatasız Parça Sayacı: {hatasiz_sayaci}")
        if not self.controller.is_running: return

        color = "#5CB85C" if genel_durum == "HATASIZ" else "#D9534F"
        self.genel_durum_label.configure(text=f"DURUM: {genel_durum}", text_color=color)
        if role_durumu: self.role_durum_label.configure(text=f"Röle: AKTİF ({int(kalan_sure)+1}s)", text_color="#5CB85C")
        else: self.role_durum_label.configure(text="Röle: PASİF", text_color="#D9534F")
        hata_metni = "Hata Detayları:\n" + ("- Yok" if not hatalar else "\n".join([f"- {h}{sayim_detay if h=='Sayım Hatası' else ''}" for h in hatalar]))
        self.hata_list_label.configure(text=hata_metni)

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
        self.log_message("Uygulama kapatılıyor...")
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