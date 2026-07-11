# ATLAS — Adaptive Thinking & Layered Autonomy System

> Your intelligent desktop co-pilot. Voice-controlled. Biometric-secured. Fully local.

[![Phase](https://img.shields.io/badge/Phase-0%20%E2%80%94%20Foundation-blue)]()
[![Version](https://img.shields.io/badge/version-0.1.0--alpha-orange)]()
[![Python](https://img.shields.io/badge/python-3.11%2B-green)]()
[![License](https://img.shields.io/badge/license-MIT-brightgreen)]()
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)]()

---

## Current Status

ATLAS is in **active, early-stage development (Phase 0 — Foundation)**, built solo and spec-first: every feature is implemented against a locked **SRS v2.0.0** document, with formal project instructions enforcing surgical edits, spec compliance, and low-bug throughput before anything ships. This README describes the full target system — features marked below by phase are the build plan, not all shipped yet. See [Roadmap](#roadmap) for what exists today versus what's planned.

---

## What is ATLAS?

ATLAS is a locally-installed AI assistant that lets you control your computer with natural language — the way Tony Stark talks to J.A.R.V.I.S. It runs on your machine, knows your voice, and only responds to you.

- **Voice-first** — say *"Hey Atlas"* and speak naturally
- **Biometric auth** — only the owner can give commands (voice print, face, fingerprint, PIN)
- **Skills-based** — file manager, web search, code executor, weather, and 13 more built-in (planned, Phase 1)
- **Your choice of voice** — 8 built-in personas (Nova, Orion, Atlas, Aria, Sage, Rex, Zara, Echo)
- **Fully local option** — runs 100% offline with Ollama + Kokoro TTS (no cloud needed)
- **Cross-platform** — Windows 10/11, macOS 12+, Ubuntu 22.04+

---

## Quick Start

### Requirements
- Python 3.11+
- 8 GB RAM minimum (16 GB recommended for local LLM)
- Microphone (for voice mode)

### Install (development)

```bash
git clone https://github.com/Zishaniitm/atlas-ai.git
cd atlas-ai

# Create virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
.venv\Scripts\activate           # Windows

# Install ATLAS and dependencies
pip install -e ".[dev]"

# First run — enrol your PIN (voice print + face auth in Phase 1)
python -m atlas setup

# Start ATLAS
python -m atlas
```

### Cloud mode (requires OpenAI API key)

```bash
# Store your key in the OS keychain (never written to disk)
python -c "import keyring; keyring.set_password('atlas-ai', 'openai_api_key', 'sk-...')"

python -m atlas
```

### Local mode (no internet required after install)

```bash
# Install Ollama — https://ollama.ai
ollama pull mistral

# Set provider to ollama in config
python -m atlas --provider ollama
```

---

## Voice Personas

ATLAS ships with 8 built-in offline personas (all powered by Kokoro TTS):

| Persona | Gender | Style |
|---------|--------|-------|
| **Atlas** (default) | Neutral | Clear, professional, calm |
| **Nova** | Female | Warm, friendly, conversational |
| **Orion** | Male | Deep, authoritative, precise |
| **Aria** | Female | Energetic, crisp, modern |
| **Sage** | Neutral | Soft, thoughtful, academic |
| **Rex** | Male | Casual, upbeat, fast-paced |
| **Zara** | Female | Professional, Indian-accented English |
| **Echo** | Neutral | Minimal, robotic, sci-fi style |

Switch persona from the HUD settings panel at any time — no restart needed.

---

## Project Structure

```
atlas-ai/
├── atlas/                  # Main Python package
│   ├── core/               # LLM client, config, event bus
│   ├── voice/               # STT, TTS, wake word, pipeline, personas
│   ├── skills/               # 13 core skills (Phase 1)
│   ├── security/auth/      # PIN, voice print, face, Hello, FIDO2
│   ├── memory/               # SQLite + ChromaDB (Phase 1)
│   ├── api/                 # FastAPI internal server (localhost:7770)
│   ├── ui/                   # PyQt6 HUD (Phase 1)
│   └── telemetry/           # Crash reporter + Sentry (opt-in)
├── config/defaults.yaml    # Default configuration
├── tests/                   # Unit + integration + E2E tests
└── installer/                # Platform installers (Phase 2)
```

---

## Authentication

ATLAS supports 5 authentication methods (Phase 0 ships PIN; others in Phase 1/2):

| Method | Hardware Needed | Phase |
|--------|----------------|-------|
| PIN / Password | None | ✅ Phase 0 |
| Voice Print | Microphone | Phase 1 |
| Face Recognition | Webcam | Phase 1 |
| Windows Hello / Touch ID | Fingerprint reader or IR camera | Phase 2 |
| FIDO2 Hardware Key | YubiKey or FIDO2 key | Phase 3 |

All biometric data is stored AES-256 encrypted on your machine. Nothing is ever uploaded.

---

## Development

```bash
# Run tests
pytest tests/unit/ -v

# Type check
mypy atlas/ --strict

# Lint
ruff check .

# Install pre-commit hooks
pre-commit install
```

### Adding a new skill

1. Create `atlas/skills/your_skill.py` inheriting `BaseSkill`
2. Declare `name`, `description`, `parameters`, `permissions`, `risk_level`
3. Implement `async def execute(...) -> SkillResult`
4. Restart ATLAS — it auto-discovers new skills

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full skill authoring guide.

---

## Roadmap

Every milestone below is scoped and gated by the project's SRS v2.0.0 — nothing merges without matching the locked spec, which keeps scope creep and regressions low even at solo-developer velocity.

| Version | Status | Key Features |
|---------|--------|-------------|
| v0.1.0-alpha | 🔨 Building (current) | Foundation — voice pipeline, PIN auth, event bus, FastAPI |
| v0.9.0-beta | 📋 Planned | 13 skills, HUD, memory, voice+face auth, Win+macOS builds |
| v1.0.0 | 📋 Planned | Full installer, 20+ skills, 3-OS, crash reporter, docs |
| v1.x.0 | 📋 Planned | Email, calendar, smart home, i18n, accessibility |
| v2.0.0 | 💡 Future | Local LLM fine-tuning, multi-agent, web frontend |

---

## Privacy

ATLAS is private by default:
- Voice audio processed locally by Whisper — never sent anywhere
- Biometric embeddings stay on your machine, AES-256 encrypted
- Cloud LLM (GPT-4o/Claude) only used if you configure an API key
- Crash reporting is opt-in and excludes all personal data

Read the full [Privacy Policy](PRIVACY.md).

---

## Author

Built and maintained solo by **Zishan**, B.S. Data Science student at IIT Madras.
Portfolio: [zishan-portfolio-eight.vercel.app](https://zishan-portfolio-eight.vercel.app/)

Issues, feedback, and early testers welcome — this is an actively evolving Phase 0 project, and the [Roadmap](#roadmap) above shows exactly where it's headed next.

---

## License

MIT License — see [LICENSE](LICENSE).
