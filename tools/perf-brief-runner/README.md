# 성과보고 러너 (Windows)

대시보드 `track record → TORUS/AI테크 → 오늘의 성과보고` 카드의 **[보고서 생성]** 버튼이
호출하는 Windows 사이드카.

## 왜 Windows 인가

`claude` CLI 가 이 PC 에만 있고 인증이 **구독 OAuth**(`~/.claude/.credentials.json`)라
collector 컨테이너로 옮길 수 없다(옮기려면 별도 Anthropic API 키 발급이 필요).
그래서 역할을 나눴다 — **계산은 컨테이너, 서사는 이 러너**.

```
[보고서 생성] 버튼
  → api  POST /api/v1/inav/perf-brief/generate?mode=daily
  → collector  (host.docker.internal:8010)
  → 러너  perf_brief_runner.py
       1. collector 의 /perf-brief/analyze 로 확정 수치 수령 (검증된 엔진 재사용)
       2. 프롬프트 = json_schema.md + 완성 보고서 2종 예시 + 확정 수치 + QA 경고
       3. claude -p --output-format json  (WebSearch 로 뉴스 조사 + 서사 작성)
       4. 수치 보존 검증 → S:\...\정기미팅\daily_YYYYMMDD.json 저장
  → 기존 /perf-brief 배선이 그대로 집어 올려 대시보드에 렌더
```

## 실행

`성과보고_러너_시작.bat` 을 더블클릭. **이 창을 닫으면 버튼이 멈춘다.**
매일 쓰려면 시작프로그램(`shell:startup`)에 바로가기를 넣어 둘 것.

확인: <http://localhost:8010/health> → `{"status":"ok","claude":true}`

## 설정 (환경변수, 전부 선택)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `PERF_BRIEF_RUNNER_PORT` | `8010` | 수신 포트 |
| `PERF_BRIEF_MODEL` | `opus` | `sonnet` 으로 낮추면 빠르고 저렴 |
| `PERF_BRIEF_TIMEOUT_S` | `900` | claude 호출 상한(초) |
| `PERF_BRIEF_DIR` | `S:\GE\Wonjae\07_회의자료\정기미팅` | 보고서·예시·스키마 폴더 |
| `PERF_BRIEF_RUNNER_TOKEN` | (없음) | 설정 시 `X-Runner-Token` 헤더 검사. collector 에도 같은 값을 주어야 함 |

`0.0.0.0` 에 바인딩하므로 사내 LAN 에서 보인다. 토큰을 걸려면 러너와 collector
(`docker-compose.yml` 의 `PERF_BRIEF_RUNNER_TOKEN`) 양쪽에 같은 값을 넣는다.

## 안전장치

- **수치 보존 검증**: 모델이 스코어카드·차트 수치를 하나라도 바꾸면 저장하지 않고 실패
  처리한다. 서사(stories·market·checkpoints·caption)만 새로 붙는 구조.
- **필수 항목 검증**: 시장 스트립·스토리 2개 이상·관전 포인트가 없으면 실패.
- **덮어쓰기 보호**: 같은 이름의 보고서가 이미 있으면 `backup/` 에 타임스탬프로 복사한 뒤
  교체한다. 손으로 만든 보고서가 조용히 사라지지 않는다.
- **원자적 저장**: `.tmp` 로 쓰고 rename — 대시보드가 반쯤 쓰인 파일을 읽지 않는다.
- **OMC 비활성화**: 서브프로세스에 `DISABLE_OMC=1` 을 주어 사용자 전역 `CLAUDE.md` 의
  오케스트레이션 레이어가 끼어들지 않게 한다.

## 실패했을 때

러너 창의 로그가 1차 자료다. 대시보드 카드에도 단계 로그가 그대로 뜬다.

| 증상 | 원인 |
|---|---|
| `러너에 연결할 수 없습니다` | .bat 이 꺼져 있음 (또는 방화벽이 8010 차단) |
| `분석 응답 이상` | collector 가 소스 엑셀을 못 읽음 — [분석 시작]으로 먼저 확인 |
| `수치 보존 위반` | 모델이 숫자를 손댐 — 재시도. 반복되면 프롬프트의 '절대 규칙' 강화 필요 |
| `claude 실패 rc=...` | 인증 만료 등 — 터미널에서 `claude` 를 한 번 실행해 로그인 상태 확인 |

수치만 급히 필요하면 **[분석 시작]**(0.5초, claude 불필요)으로 대체할 수 있다.
