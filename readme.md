# 🕷️ S.P.I.D.Y. AI

### Next-Gen Autonomous Desktop Voice Assistant & Cyber Holographic HUD
**Created by Abhay Patil**

[![License: MIT](https://img.shields.io/badge/License-MIT-cyan.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![UI: Dynamic Island & Orb](https://img.shields.io/badge/Interface-Dynamic%20Island%20%26%20Orb-00f2ff.svg)](ui_island.py)
[![Model: Gemini Live API](https://img.shields.io/badge/Model-Gemini%20Multimodal%20Live-orange.svg)](https://ai.google.dev/)

---

## ⚡ Overview

**S.P.I.D.Y. AI** is a real-time, low-latency multimodal desktop companion built on Google's Gemini Multimodal Live API. It can hear your voice, see your screen or webcam, understand natural instructions, execute complex multi-step computer tasks, and speak back naturally with zero cloud subscriptions.

Featuring a custom-designed **Futuristic Holographic HUD Dynamic Island Bar**, S.P.I.D.Y. floats non-intrusively at the top of your desktop:
- **Intelligent Auto-Hide**: Collapses into a minimal micro-notch at your screen bezel when silent.
- **Voice-Reactive Expansion**: Automatically expands into a sleek 44px cyber HUD pill as soon as you speak.
- **Vector Spider HUD Dial**: Stylized Spider-Man avatar HUD with glowing angular cyan eyes, crimson accent arc, and outer neon glow.
- **Dual-Tone Soundwave**: Real-time scarlet & electric cyan audio visualizer responding to live mic and speech.
- **Ambient Orb Mode**: Alternative glowing desktop orb that sits anywhere on your screen.

---

## 🚀 Key Features

| Capability | Description |
| :--- | :--- |
| 🕷️ **Holographic HUD Island** | Sleek 44px dynamic floating bar with auto-hide notch, vector Spider avatar, and mute controls |
| 🔮 **Ambient Desktop Orb** | Alternative minimal desktop orb with pulsing energy auras and position memory |
| 🎙️ **Real-Time Voice Streaming** | Ultra-low latency bidirectional audio powered by Gemini Multimodal Live API over WebSockets |
| 👁️ **Visual Intelligence** | Real-time screen capture and webcam inspection to analyze error dialogs, IDE code, websites, or images |
| 📂 **Smart App & File Launcher** | Opens files, folders, or workspaces in user-preferred applications (e.g., *"Open my project in AntiGravity"* or *"Open notes in VS Code"*) |
| 💬 **WhatsApp Automation** | Headless WhatsApp integration to read unread messages, look up saved contact names, and send replies hands-free |
| 🌐 **Live Web Automation** | Built-in Playwright headless browser control to navigate websites, click elements, fill forms, and search the web |
| 🛡️ **Autonomous Problem Solving** | Integrated Hermes execution engine for multi-step terminal commands, script execution, and workspace automation |
| 🌤️ **Voice Weather & News** | Spoken weather telemetry and news summaries delivered aloud without forcing open browser tabs |
| ⌨️ **Global Hotkeys** | Press **`Ctrl+Space`** or **`Ctrl+A`** anywhere in Windows to wake, command, or expand instantly |
| 🧠 **Persistent Long-Term Memory** | Remembers facts about you, your preferences, and projects across reboots |

---

## 🛠️ Quickstart & Setup Guide

### 1. Prerequisites
- **Operating System**: Windows 10/11 (fully supported with global hotkeys & pywin32), macOS, or Linux.
- **Python**: Version `3.10`, `3.11`, or `3.12` installed ([Download Python](https://www.python.org/downloads/)).
- **Gemini API Key**: Free API key from [Google AI Studio](https://aistudio.google.com/app/apikey).

---

### 2. Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Abhayp56/SPIDY-AI.git
   cd SPIDY-AI
   ```

2. **Create and activate a virtual environment (recommended)**:
   ```bash
   # Windows
   python -m venv venv
   venv\Scripts\activate

   # macOS / Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   python setup.py
   ```
   *Or install directly via pip:*
   ```bash
   pip install -r requirements.txt
   playwright install chromium firefox
   ```

---

### 3. Configuration

1. Copy the example configuration file:
   ```bash
   cp config/api_keys.json.example config/api_keys.json
   ```
2. Open `config/api_keys.json` and paste your Gemini API key:
   ```json
   {
     "gemini_api_key": "YOUR_GEMINI_API_KEY_HERE",
     "ui_mode": "island",
     "assistant_name": "S.P.I.D.Y.",
     "voice_name": "Alnilam"
   }
   ```
   *(Optional search provider keys for Serpstack, Zenserp, or GCrawl can also be added here).*

---

### 4. Launching S.P.I.D.Y.

Run the main application:
```bash
python main.py
```

- When launched, the **Cyber HUD Island Bar** floats smoothly at the top of your screen.
- Say **"Hey Spidy"** or press **`Ctrl+Space`** / **`Ctrl+A`** to speak!
- Click the **Microphone** icon on the HUD to mute or unmute.
- Click the **•••** menu to switch between **Island Bar Mode** and **Desktop Orb Mode**, toggle Auto-Hide, or adjust settings.

---

## 🎮 Voice Commands & Examples

- **Preferred App Opening**:
  - *"Spidy, open my Mark-LV folder in AntiGravity."*
  - *"Open project in VS Code."*
- **WhatsApp**:
  - *"Read my unread WhatsApp messages."*
  - *"Send a message to John on WhatsApp saying I'll be there in 10 minutes."*
- **Computer Controls & Settings**:
  - *"Set volume to 50 percent."*
  - *"Turn on dark mode."*
  - *"Check my battery and CPU usage."*
- **Vision & Screen**:
  - *"Look at my screen and tell me what error this terminal is showing."*
  - *"Inspect what website is open."*
- **Information & Autonomous Tasks**:
  - *"What is the weather today?"*
  - *"Create a Python script that organizes my downloads folder."*

---

## 🔒 Privacy & Local Security

- **Zero Cloud Middleman**: Your computer connects directly and securely via encrypted TLS to Google's Gemini Live API.
- **Local Credentials**: `config/api_keys.json`, `data/`, and personal memory databases are strictly excluded by `.gitignore` so your private tokens and WhatsApp cookies never leak.

---

## 📜 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for details.

---

## 👤 Author & Credits

- **Creator & Lead Developer**: [Abhay Patil](https://github.com/Abhayp56)
- **Upstream Autonomous Tools**: Powered by open-source tool execution frameworks.
- ⭐ If you like this project, feel free to **star the repository**!
