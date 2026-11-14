# Vendored MOSS-TTS-Nano runtime

`ort_cpu_runtime.py` is copied unchanged from the upstream source repository at commit `8b7bcc9341b3b4ef3a3a58ba1338a7d85ff133eb` (2026-09-06), file `ort_cpu_runtime.py`.

- Source: https://github.com/OpenMOSS/MOSS-TTS-Nano
- License: Apache-2.0, copied to `LICENSE` in this directory.

The upstream ONNX entry point imports PyTorch and torchaudio for reference audio loading and text normalization. The probe only uses the built-in voice presets, whose audio codes are already in `browser_poc_manifest.json`, so the torch-free runtime file is enough. Vendoring one file pinned by commit is the smallest way to run the same graph code without a PyTorch dependency; reimplementing it would drift from the published runtime.

`onnx_tts_runtime.py` from the same commit is not copied. It adds PyTorch and WeTextProcessing to the import path.
