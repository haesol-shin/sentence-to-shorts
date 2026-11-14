# 동봉 ffmpeg 실측

이 문서는 imageio-ffmpeg wheel에 동봉된 ffmpeg 실행 파일의 실측 결과를 모은다. probe 코드는 제품 코드가 아니며 제품 의존성과 lockfile에 넣지 않는다. 수치는 실제 실행에서만 옮기고 없는 값을 추정하지 않는다.

## 실행

- pull request는 `.github/workflows/probe-ffmpeg.yml`의 `ubuntu-24.04` 작업을 돌린다.
- Windows 작업은 `workflow_dispatch`의 `windows` 입력이 true일 때만 `windows-latest`에서 돈다. Windows 실행은 설치 작업 뒤로 미룬다.
- 실행마다 `result.json`과 `summary.md`를 OS별 artifact로 올린다. 이름은 `probe-linux-x86_64`와 `probe-windows-x86_64`다.
- harness만 다시 돌리는 로컬 명령은 `uv run --with imageio-ffmpeg==0.8.1 python probes/ffmpeg/run_probe.py --output probes/ffmpeg/.local/probe`다. 이 결과는 x64 실측이 아니므로 아래 표에 옮기지 않는다.

## 측정 규칙

- 표의 행은 artifact의 `result.json`에서 그대로 옮기고, artifact를 남긴 workflow 실행을 PR에 적는다.
- 모든 시험은 `checks`에 `pass` 또는 `fail`로 남는다. 시험 대상의 실패는 결과이고 workflow는 성공으로 끝난다. workflow 실패는 harness 오류만 뜻한다.
- 바이너리 사실은 절대 경로, bytes, SHA-256, `-version` 첫 줄, `build`, `configuration`, 라이선스다. 라이선스는 `configuration`의 `--enable-gpl`과 `--enable-version3`으로 GPL 또는 LGPL을 가른다.
- ffprobe는 wheel에 들어 있지 않다. metadata는 `ffmpeg -i`의 stream 줄과 null decode의 frame 수로 읽고 그 방법을 `binary.ffprobe.metadata_method`에 적는다.
- loudnorm은 2-pass로 적용하고 결과 파일을 다시 loudnorm으로 재어 `-16 LUFS` ±1과 true peak `-1 dBTP` 이하를 판정한다.
- sidechaincompress는 speech가 큰 구간에서 music의 RMS 감소가 2 dB 이상인지로 ducking을 판정한다.
- Windows 행은 같은 표에 OS 열로 더한다.

결과는 Actions 실행 `43604133062`(2026-11-14)의 `probe-linux-x86_64` artifact에서 옮겼다.

## 시험 항목

| check | 확인 |
|---|---|
| `rgb24_stdin_h264` | raw RGB24 stdin을 H.264 yuv420p 1080x1920 30fps로 encode하고 decode frame 수를 센다 |
| `concat_copy` | 같은 규격 clip 3개를 concat demuxer로 재 encoding 없이 붙인다 |
| `aac_mux` | 무음 clip에 AAC 44.1kHz를 mux한다 |
| `loudnorm_two_pass` | 2-pass loudnorm 뒤 통합 음량과 true peak를 다시 잰다 |
| `sidechaincompress_ducking` | speech가 큰 구간에서 music의 RMS 감소를 잰다 |
| `bgm_loop_crossfade` | BGM을 반복하고 두 구간을 crossfade한다 |
| `protocol_whitelist_file_pipe` | file,pipe만 허용하고 pipe 입력을 받으며 data protocol을 거절한다 |
| `decode_mp3` | 올린 mp3를 decode한다 |
| `decode_m4a` | 올린 m4a를 decode한다 |
| `decode_ogg` | 올린 ogg를 decode한다 |
| `decode_wav` | 올린 wav를 decode한다 |

## 결과

### 바이너리

| OS | runner | 경로 | bytes | SHA-256 | version | configuration | 라이선스 | ffprobe |
|---|---|---|---|---|---|---|---|---|
| Linux | ubuntu-24.04 | `$RUNNER_TEMP/probe-env/lib/python3.11/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v9.0.2` | 172692552 | `0d709a0bed1a43f24cd2c420878c63afea4580671b6949ad19ed124572f3bc3d` | `n9.0.2-17-g2a571b6068-20260930` | `--enable-gpl --enable-version3` (전문은 아래) | `GPL-3.0-or-later` | 없음 (`bundled` false, `system` false); metadata는 `ffmpeg -i` stream 줄과 null decode frame 수 |

- artifact의 경로는 runner 임시 폴더의 절대 경로다. 공개 문서 규칙에 따라 접두사를 `$RUNNER_TEMP`로 적었다.
- `-version` 첫 줄: `ffmpeg version n9.0.2-17-g2a571b6068-20260930 Copyright (c) 2000-2026 the FFmpeg developers`.
- build: `gcc 16.2.0 (crosstool-NG 1.29.0.7_b1a94f6)`.
- wheel은 imageio-ffmpeg 0.8.1이고 실행 파일은 그 wheel의 `binaries` 폴더에 있다.
- 라이선스는 `configuration`의 `--enable-gpl`과 `--enable-version3`으로 GPL-3.0-or-later다.
- configuration 전문:

```text
--prefix=/ffbuild/prefix --pkg-config-flags=--static --pkg-config=pkg-config --cross-prefix=x86_64-ffbuild-linux-gnu- --arch=x86_64 --target-os=linux --enable-gpl --enable-version3 --disable-debug --enable-iconv --enable-zlib --enable-libxml2 --enable-libsoxr --enable-openssl --enable-libvmaf --enable-libxcb --enable-xlib --enable-fontconfig --enable-libharfbuzz --enable-libfreetype --enable-libfribidi --enable-vulkan --enable-libdav1d --enable-libvorbis --enable-librav1e --enable-librsvg --enable-libpulse --enable-gmp --enable-lzma --enable-liblcevc-dec --enable-opencl --enable-amf --enable-libaom --enable-avisynth --enable-chromaprint --enable-libdavs2 --enable-libdvdread --enable-libdvdnav --disable-libfdk-aac --enable-ffnvcodec --enable-cuda-llvm --enable-frei0r --enable-libgme --enable-libkvazaar --enable-libaribb24 --enable-libaribcaption --enable-libass --enable-libbluray --enable-libjxl --enable-libmp3lame --enable-libopus --enable-libplacebo --enable-librist --enable-libssh --enable-libtheora --enable-libvpx --enable-libwebp --enable-libzmq --enable-lv2 --enable-libvpl --enable-openal --enable-liboapv --enable-libopencore-amrnb --enable-libopencore-amrwb --enable-libopenh264 --enable-libopenjpeg --enable-libopenmpt --enable-librubberband --disable-schannel --enable-sdl2 --enable-libsnappy --enable-libsrt --enable-libsvtav1 --enable-libtwolame --enable-libuavs3d --enable-libdrm --enable-vaapi --enable-libvidstab --enable-libvvenc --disable-whisper --enable-libx264 --enable-libx265 --enable-libxavs2 --enable-libxvid --enable-libzimg --enable-libzvbi --extra-cflags=-DLIBTWOLAME_STATIC --extra-cxxflags= --extra-libs='-lgomp -ldl' --extra-ldflags=-pthread --extra-ldexeflags= --cc=x86_64-ffbuild-linux-gnu-gcc --cxx=x86_64-ffbuild-linux-gnu-g++ --ar=x86_64-ffbuild-linux-gnu-gcc-ar --ranlib=x86_64-ffbuild-linux-gnu-gcc-ranlib --nm=x86_64-ffbuild-linux-gnu-gcc-nm --extra-version=20260930
```

### 시험

| OS | check | status | 측정값 | 비고 |
|---|---|---|---|---|
| Linux | `rgb24_stdin_h264` | pass | 30 frames, 1.0 s, 1080x1920, yuv420p, fps 30.0, 17846 bytes; 0.439 s | - |
| Linux | `concat_copy` | pass | 3 clips, 30 frames, 1.0 s, h264/mp4; 0.53 s | 재 encoding 없음 |
| Linux | `aac_mux` | pass | h264 + AAC 44100 Hz, 1.0 s, 33951 bytes; 0.5 s | - |
| Linux | `loudnorm_two_pass` | pass | pass1 -25.25 LUFS / -20.4 dBTP, output -16.05 LUFS / -11.16 dBTP, target -16.0 LUFS / -1.0 dBTP; 0.257 s | 목표 -16 LUFS ±1, true peak -1 dBTP 이하 |
| Linux | `sidechaincompress_ducking` | pass | music -19.831 dB, ducked -36.714 dB, reduction 16.883 dB; 0.213 s | 감소 기준 2.0 dB 이상 |
| Linux | `bgm_loop_crossfade` | pass | loop 2.0 s, crossfade 0.5 s (구간 3.5 s); 0.093 s | - |
| Linux | `protocol_whitelist_file_pipe` | pass | pipe frames 5, data 거절; 0.146 s | - |
| Linux | `decode_mp3` | pass | mp3, 1.0 s, 17179 bytes, libmp3lame; 0.057 s | - |
| Linux | `decode_m4a` | pass | AAC, 1.0 s, 15806 bytes, encoder aac; 0.033 s | - |
| Linux | `decode_ogg` | pass | vorbis, 1.0 s, 5829 bytes, libvorbis; 0.034 s | - |
| Linux | `decode_wav` | pass | pcm_s16le, 1.0 s, 88278 bytes; 0.025 s | - |

`summary`는 total 11, passed 11, failed 0, harness errors 0이다.

## 결정 gate

- 통과하면 제품은 imageio-ffmpeg의 동봉 실행 파일 경로를 쓴다.
- 실패하면 대안 정적 빌드 하나를 골라 URL, SHA-256, 라이선스를 이 문서에 적고 runtime lock에 넣는다.
- 이번 Linux 실행은 11개가 모두 `pass`라서 통과 쪽이다. 제품은 동봉 실행 파일 경로를 쓴다. Windows 행은 R1 뒤에 더한다.
