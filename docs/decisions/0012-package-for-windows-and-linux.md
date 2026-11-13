# 0012 Windows와 Linux 설치물을 제공한다

## Status

Accepted

## Date

2026-11-14

## Context

사용자는 개발 환경과 모델을 직접 설치하지 않아야 한다. 개발과 배포의 의존성 목록이 달라져서는 안 된다.

## Decision

Windows는 관리자 권한이 필요 없는 사용자별 설치 exe로 제공한다. Linux는 tarball과 시작 스크립트로 제공한다. Python과 CPU wheel은 배포물에 동봉한다. 모델은 첫 실행에 manifest와 SHA-256을 검증해 준비한다. 개발과 배포는 같은 runtime manifest를 사용한다. 배포판의 기본 연결 방식은 사용자 API key다. 현재 빌드의 key 등록과 실호출은 [보류 결정](0020-defer-release-api-key-registration.md)을 따른다. 실제 새 Windows와 Linux 환경에서 설치와 영상 생성을 검증한다. 현재 release profile의 실제 API 호출은 미실행으로 남긴다. 선택 TTS와 렌더와 설치 검증은 실호출과 구분한다.

## Basis

- Team decision: 지원 OS는 Windows와 Linux다.
- Team decision: 사용자가 아닌 소프트웨어가 runtime을 준비한다.
- Team decision: Windows 설치 exe와 Linux tarball을 제공한다.
- Team decision: Python과 CPU wheel 동봉과 모델 checksum 검증을 적용한다.

## Considered options

- OS별 설치물과 첫 모델 준비: 사용자 설치 부담을 줄여 선택한다.
- 사용자에게 Python과 모델 설치 요구: 제품 요구와 맞지 않아 선택하지 않는다.
- PATH를 비운 CI만으로 완료 판단: 실제 새 환경 시험을 대체하지 못해 선택하지 않는다.

## Consequences

- 양 OS의 설치와 재실행을 별도로 검증해야 한다.
- 서명 없는 Windows 설치물의 경고를 확인해야 한다.
- 모델과 binary의 라이선스 고지를 배포물에 포함해야 한다.
