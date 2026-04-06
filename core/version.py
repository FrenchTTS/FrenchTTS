"""
FrenchTTS — build identity.

Overwritten at build time by the GitHub Actions workflow before PyInstaller runs.
At runtime: BUILD_ID is "dev" in source, or a 7-char commit SHA in the frozen exe.
"""

BUILD_ID = "dev"   # replaced with: git rev-parse --short HEAD
