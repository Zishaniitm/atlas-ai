# ATLAS — Adaptive Thinking & Layered Autonomy System

> Your intelligent desktop co-pilot. Voice-controlled. Biometric-secured. Fully local.

[![Version](https://img.shields.io/badge/version-0.9.0--beta.1-orange)]()
[![Python](https://img.shields.io/badge/python-3.11%2B-green)]()
[![License](https://img.shields.io/badge/license-MIT-brightgreen)]()
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)]()

---

## What is ATLAS?

ATLAS is a locally-installed AI assistant that lets you control your computer with natural language — the way Tony Stark talks to J.A.R.V.I.S. It runs on your machine, knows your voice, and only responds to you.

- **Voice-first** — say *"Hey Atlas"* and speak naturally
- **Biometric auth** — only the owner can give commands (PIN, voice print, face recognition)
- **13 built-in skills** — file manager, web search, code executor, weather, Wikipedia, and more
- **8 voice personas** — Atlas, Nova, Orion, Aria, Sage, Rex, Zara, Echo
- **Fully local option** — runs 100% offline with Ollama + Kokoro TTS
- **Cross-platform** — Windows 10/11, macOS 12+, Ubuntu 22.04+

---

## Quick Start

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/atlas-ai.git
cd atlas-ai

# Virtual environment
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
# source .venv/bin/activate     # macOS / Linux

# Install
pip install -e ".[dev]"

# Store API key in OS keychain (never written to any file)
python -c "import keyring; keyring.set_password('atlas-ai', 'openai_api_key', 'sk-...')"

# Run ATLAS
python -m atlas
```

Say **"Hey Atlas"** to start. On first run, you'll be prompted to set a PIN.

---

## Voice Personas

| Persona | Style |
|---------|-------|
| **Atlas** (default) | Clear, professional, calm |
| **Nova** | Warm, friendly, conversational |
| **Orion** | Deep, authoritative, precise |
| **Aria** | Energetic, crisp, modern |
| **Sage** | Soft, thoughtful, academic |
| **Rex** | Casual, upbeat, fast-paced |
| **Zara** | Professional, Indian-accented English |
| **Echo** | Minimal, robotic, sci-fi |

Switch persona: **HUD Settings → Voice → Persona Picker**

---

## Built-in Skills (Phase 1)

| Skill | What it does |
|-------|-------------|
| File Manager | Create, move, copy, delete, search files |
| App Launcher | Open/close/focus applications by name |
| Web Search | DuckDuckGo search with summaries |
| Web Browsing | Autonomous browser via Playwright |
| Code Executor | Run Python/bash scripts safely |
| System Monitor | CPU, RAM, disk, battery stats |
| Calculator | Math + unit conversions |
| Wikipedia | Article summaries |
| Weather | Current + 7-day forecast (Open-Meteo, free) |
| Date & Time | Time/date + alarms |
| Clipboard | Read/write system clipboard |
| Screenshot + OCR | Capture screen + extract text |
| Volume Control | Get/set/mute system audio |

---

## Project Structure

```
atlas/
├── atlas/
│   ├── core/          # LLM client, config, event bus, orchestrator
│   ├── voice/         # STT (Whisper), TTS (Kokoro), wake word, pipeline
│   ├── skills/        # 13 core skills + BaseSkill interface
│   ├── memory/        # SQLite + ChromaDB async memory
│   ├── security/auth/ # PIN auth (+ voice print/face in Phase 2)
│   ├── api/           # FastAPI server on localhost:7770
│   └── telemetry/     # Crash reporter + optional Sentry
├── config/
│   └── defaults.yaml  # Full config schema
└── tests/             # Unit + integration + E2E tests
```

---

## Development

```bash
# Run unit tests
pytest tests/unit/ -v

# Type check
mypy atlas/ --strict

# Lint
ruff check .

# Install pre-commit hooks
pre-commit install
```

---

## Roadmap

| Version | Status | Key Features |
|---------|--------|-------------|
| v0.1.0-alpha | ✅ Done | Foundation: config, events, PIN auth, API |
| v0.9.0-beta.1 | 🔨 Building | 13 skills, memory, orchestrator, voice pipeline |
| v1.0.0 | 📋 Planned | Installer, HUD, face auth, voice print auth |
| v1.x.0 | 💡 Future | Email, calendar, smart home, i18n |
| v2.0.0 | 💡 Future | Local LLM fine-tuning, multi-agent |

---

## Privacy

- Voice processed locally by Whisper — never sent anywhere
- Biometrics encrypted (AES-256) on your machine only
- Cloud LLM only used if you configure an API key
- Crash reporting is opt-in, off by default

See [PRIVACY.md](PRIVACY.md) for the full policy.

---

## License

MIT — see [LICENSE](LICENSE).
