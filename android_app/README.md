# Antigravity Golf App

This is the native Android application wrapper for the SkyTrak Bridge & Vision Engine. 
It uses WebViews to display the immersive shot tracer and dashboard, while implementing native Android UI components for networking resilience, Coaching REST API fetching, and WebSocket status overlays.

## 🛠 Required PC Setup
For this application to connect and work properly, you must have the bridge logic running on a PC on the **same WiFi network** as your Android device.
1. Run the Python bridge & coaching API:
   ```bash
   python main.py
   ```
2. Note your PC's local IP address (e.g., `192.168.1.150`).

## 📱 How to Open in Android Studio
This project is pure Android Gradle.
1. Open Android Studio.
2. Click **File > Open**.
3. Select the `antigravity_golf_app` folder (the parent directory containing this `README.md`).
4. Android Studio will automatically resolve the `build.gradle.kts` files and index the SDK. **No manual fixes are required.**

## 🚀 How to Run on Device
1. Connect your Android phone to your PC via USB or Wireless Debugging.
2. Ensure **Developer Options** and **USB Debugging** are enabled on your phone.
3. In Android Studio, select your device from the dropdown toolbar at the top.
4. Click the green **Run** arrow (or press `Shift + F10`).
5. When the app launches, enter your PC's IP Address and the ports (defaults: Web 8080, Coaching 8766).
