# 접근 제어

접근 계약은 [CONTRACTS §3](../../../docs/CONTRACTS.md#3-http-api-공통-규칙)과 [§13.2](../../../docs/CONTRACTS.md#132-접근-제어)가 원본이다.

## Pairing과 세션

신뢰하는 로컬 launcher는 `runtime.access.issue_pairing_code()`로 새 코드를 발급하고 사용자 화면에 표시한다. 새 코드는 이전 코드를 대체하며, 5분 동안 한 번만 사용할 수 있다. 코드를 query string이나 로그에 넣지 않는다. 브라우저는 같은 origin의 `POST /api/v1/session/pair`로 코드를 교환한다.

직접 실행할 때는 로컬 터미널에 pairing fragment URL을 표시한다. stdout이 리디렉션되면 제어 터미널로 표시하고, 제어 터미널도 없으면 시작을 명시적으로 거절한다. 로그에는 코드를 기록하지 않는다. GUI launcher는 `create_app(pairing_display=...)`에 fragment URL을 신뢰하는 로컬 화면으로 전달하는 함수를 제공한다.

실패한 pairing은 프로세스 전체에서 1분에 5회까지 허용한다. 세션 cookie는 HttpOnly, SameSite=Strict, Path=/이며 포트별 이름을 사용한다. 세션과 CSRF token은 프로세스 메모리에만 보관하므로 재시작하면 다시 pairing해야 한다. 새 탭과 새로고침은 같은 origin에서 `GET /api/v1/session/csrf`로 token을 받는다. Origin과 Fetch Metadata가 있으면 다른 출처를 거절한다. 평문 LAN에서는 두 헤더가 모두 생략될 수 있으므로 필수로 요구하지 않으며, 유효한 Strict 세션 cookie와 브라우저의 동일 출처 응답 읽기 제한으로 보호한다. CORS를 허용하지 않는다. token은 브라우저의 영속 저장소에 넣지 않는다.

## LAN

기본 bind는 `127.0.0.1`이다. `APP_LAN=1`인 경우에만 설정한 `bind_host`를 사용한다. 허용 Host는 loopback 이름과 LAN 모드의 구체적인 bind 주소 또는 설정 이름이며 포트까지 검사한다. wildcard bind 주소 자체는 허용 Host가 아니다. LAN 모드에서는 API 문서 화면이 비활성화되며 debug와 reload를 켜지 않는다.

평문 LAN HTTP는 합성 자료 시험에만 사용한다. 같은 네트워크의 도청과 변조를 방어하지 못한다. 민감한 실제 자료는 평문 LAN으로 전송하지 않는다. credentials 변경은 연결의 실제 peer IP와 Host가 모두 loopback일 때만 허용한다. 전달된 proxy header를 loopback 판단에 사용하지 않는다.

## 멱등 요청과 업로드

키를 선언한 API는 8~64자의 `Idempotency-Key`를 요구한다. 기존 SQLite 저장소가 키와 경로, digest, 응답을 24시간 보관한다. 같은 요청이 실행 중이면 재시도 가능한 429를 반환하고, 다른 요청에 같은 키를 사용하면 409를 반환한다. 서버 오류와 실행 도중의 예외는 예약을 해제한다.

저장소를 열기 전에 `state.db.lock`의 OS 독점 잠금을 비차단 방식으로 확보한다. 같은 데이터 디렉터리의 두 번째 서버는 DB를 열거나 pending 예약을 정리하지 않고 시작을 거절한다. 정상 종료와 프로세스 종료는 잠금을 해제하므로 이후 실행은 중단된 예약을 복구할 수 있다. 잠금 파일은 삭제하지 않는다.

JSON digest는 계약의 정수 전용 canonical JSON을 따른다. multipart digest는 `file` 파트의 SHA-256과 나머지 문자열 필드의 canonical JSON을 결합하며 filename과 boundary는 포함하지 않는다. 중복 필드와 미완성 multipart는 거절한다. 요청은 cache 디렉터리의 임시 파일로 스풀하며 파일 bytes와 form bytes를 별도로 제한한다. 한도를 넘으면 413으로 중단하고 임시 파일을 닫는다. 인증 검사 전에는 업로드 본문을 읽지 않는다.

JSON 요청 본문은 1MiB까지 허용한다. 업로드 경로는 본문을 읽기 전에 multipart 형식을 검사한다. multipart form 값의 합계는 64KiB, envelope overhead는 파일 상한에 추가로 1MiB까지 허용한다.
