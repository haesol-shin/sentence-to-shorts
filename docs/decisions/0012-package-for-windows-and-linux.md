# 0012 Windows와 Linux 설치물을 제공한다

이 문서는 OS별 설치물 구조의 결정 기록이다.

Status: Accepted | Date: 2026-11-14

## Context

사용자에게 개발 환경 설치를 요구하지 않아야 한다.

## Decision

Windows는 관리자 권한 없는 사용자별 exe, Linux는 tarball과 시작 스크립트다. Python과 CPU wheel을 동봉한다. 모델은 첫 실행에 manifest와 SHA-256으로 준비한다. 개발·배포는 같은 manifest를 쓴다.

## Consequences

새 양 OS에서 설치·재실행·영상 생성을 검증한다. 서명 없는 설치 경고와 모델·binary 라이선스를 확인한다. API 실호출 증거와 설치 증거는 [CONTRACTS](../CONTRACTS.md#현재-검증-범위)처럼 구분한다.
