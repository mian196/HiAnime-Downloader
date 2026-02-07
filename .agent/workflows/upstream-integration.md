---
description: Safely integrate features from upstream HianimeDownloader repository
---

# Upstream Feature Integration Workflow

This workflow guides you through safely integrating features from the source [HianimeDownloader](https://github.com/gheatherington/HianimeDownloader) repository.

## Pre-requisites

Ensure you have cloned the upstream repositories into `scripts/` (which is `.gitignore`'d):

```bash
cd scripts/
git clone https://github.com/gheatherington/HianimeDownloader.git
git clone https://github.com/pratikpatel8982/yt-dlp-hianime.git
```

## Steps

### 1. Update Reference Repositories

// turbo
```bash
cd scripts/HianimeDownloader && git pull origin main
```

### 2. Identify the Feature

- Read the relevant code in `scripts/HianimeDownloader/`
- Understand how the feature is implemented
- Note all dependencies and imports

### 3. Analyze Local Architecture

Before integrating, verify:
- Does this feature fit our 3-stage parallel pipeline?
- Are there conflicts with existing threading model?
- Will it break any current functionality?

### 4. Safety Checklist

- [ ] Feature does not depend on removed extractors (Instagram, General)
- [ ] Feature does not rely on Chrome/Selenium (we use yt-dlp plugin)
- [ ] Feature is compatible with our `.env` configuration system
- [ ] Feature works with thread-safe queues and locks
- [ ] Feature handles graceful shutdown (`shutdown_event`)

### 5. Adapt the Feature

- Port code to fit existing architecture
- Use our logging system (`ThreadLogger`) instead of basic prints
- Add configuration options to `config.py` and `.env.example`
- Follow existing code style and patterns

### 6. Test Integration

// turbo
```bash
python -m py_compile main.py
python -m py_compile extractors/hianime.py
```

### 7. Verify Functionality

```bash
python main.py --help
python main.py -s "test" --fetch-only
```

## Important Notes

> **WARNING**: My tool does not implement every feature from the source. Do NOT add missing logic unless explicitly requested.

> **CAUTION**: Never blindly copy-paste. Always adapt to fit the existing parallel pipeline architecture.
