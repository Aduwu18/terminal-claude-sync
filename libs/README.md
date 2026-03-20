# Precompiled Dependencies

This directory contains unpacked Python packages for "plug-and-play" deployment.

## How to Generate

```bash
# From project root
pip install -t libs/ -r requirements.txt
```

## Requirements

- Python 3.11 (must match container's Python version)
- Linux x86_64 (for .so compatibility)

## Why Unpacked?

PYTHONPATH can only import from unpacked directories, not from .whl files directly.