# TTS candidate probe

Four TTS candidates are measured with one harness and one script so later product work starts from real CPU numbers instead of estimates. This directory is probe code: it is not a product dependency and it stays out of the product lockfiles.

## Layout

| Path | Role |
| --- | --- |
| `texts.json` | Fixed comparison script, eight Korean sentences and two English sentences |
| `common/harness.py` | Shared measurement loop, `result.json` writer, RSS sampler and watchdog |
| `common/run_limited.py` | Runs install and download commands with a time limit and kills the process tree on timeout |
| `common/fetch_models.py` | Downloads the pinned snapshots named in a candidate `models.json` |
| `common/record_failure.py` | Writes a result when setup fails before synthesis |
| `common/summary.py` | Renders one result for the job summary |
| `make_listening_pack.py` | Normalises successful WAV files to -16 LUFS with a peak ceiling and hides candidate names behind letters |
| `qwen3-tts-0.6b/`, `qwen3-tts-1.7b/` | Official `qwen-tts` package, CustomVoice preset speakers |
| `moss-tts-nano-100m/` | Torch-free ONNX Runtime path with the vendored upstream runtime file |
| `chatterbox-multilingual-v3/` | q4 ONNX Runtime path with the published graph contract |
| `tests/` | Harness and listening pack tests that run on any host |

Each candidate directory holds `synth.py` with the common CLI, a hash-pinned `requirements.txt`, its `requirements.in` input and a `models.json` with full revisions. `synth.py` and `result.json` read the checkpoint, revision and local directory from `models.json`; the revisions are not repeated in code or documents.

## Run

On a runner with the candidate environment:

```sh
python probes/tts/<candidate>/synth.py --texts probes/tts/texts.json --out out --threads 4
```

The harness starts the model, synthesises the first text once as warmup, then every text three times, and writes `out/result.json` plus `out/wav/<text>.wav`. `cold_start_ms` runs from the measured process start to model ready. `first_wav_ms` runs from the same process start to the first finished WAV; `warmup_synth_ms` is the synthesis part alone. Engine failures are recorded in `result.json` and the script exits 0. Exit code 3 means a stage hit its timeout and the result holds the timeout failure. Any other non-zero exit is a harness error.

`PROBE_START_MS` is the wall-clock start of the process in milliseconds. The workflow sets it before Python starts so cold start includes interpreter and import time. Without it the script falls back to its own start and records `cold_start_source`.

The listening pack consumes artifact directories:

```sh
python probes/tts/make_listening_pack.py --artifacts artifacts --out pack --key key/key.json
```

`pack/` holds one letter per candidate and one subdirectory per runner OS, for example `pack/A/linux/K1.wav`. Each clip is normalised to -16 LUFS and its peak is kept below -1 dBFS; clips shorter than the standard 0.4 s BS.1770 block are measured with a smaller block, and a clip that cannot meet both conditions keeps its measured output loudness with `target_met: false`. `key/key.json` holds the mapping and is uploaded as a separate artifact.

Model snapshots, the Hugging Face cache and the probe workspace stay under `.local/probe/`, which git ignores.

## Workflow

`.github/workflows/probe-tts.yml` runs on pull requests that touch `probes/tts/**` and on manual dispatch.

- The matrix has four candidates and `ubuntu-24.04`. `windows-latest` entries are added only when the dispatch input `windows` is true.
- `fail-fast` is false and no secret is used.
- The dispatch input `threads` sets the intra-op thread count, default 4.
- A job installs and downloads within a 30 minute limit per step, records a timeout as `install_timeout` or `download_timeout`, measures, writes the job summary and uploads `result.json` with the WAV files. A failed install, download, load or synthesis is a result, not a failed job.
- The `pack` job downloads every candidate artifact, builds the blind listening pack and uploads `listening-pack` and `listening-key`.

## Local checks

These run on an aarch64 host without x64 model runtimes:

```sh
python -m py_compile probes/tts/common/*.py probes/tts/*/synth.py probes/tts/make_listening_pack.py
uv run --with numpy==2.4.4 --with soundfile==0.14.0 --with pyloudnorm==0.2.0 --with psutil==7.2.2 python -m unittest discover -s probes/tts/tests -v
```

Workflow syntax is checked with `actionlint` when it is available. Candidate environments themselves run only in GitHub Actions.

## Requirements

`requirements.txt` files are universal CPython 3.11 resolutions of the sibling `requirements.in`, with hashes for both Ubuntu and Windows wheels. Regenerate them from the repository root with:

```sh
uv pip compile probes/tts/<candidate>/requirements.in --python-version 3.11 --universal --generate-hashes --no-header -o probes/tts/<candidate>/requirements.txt
```

The Qwen candidates also install CPU builds from the PyTorch CPU index; add `--emit-index-url --index https://download.pytorch.org/whl/cpu` to keep the extra index line. Their dependency tree is the one `qwen-tts` declares, including packages the probe does not call such as gradio, so the install cost in the artifact is the real package cost.
