# 산업 밸류체인 데이터

`/research/valuechain` 화면의 원본. 저장하면 API 가 다음 요청에서 다시 읽는다(재시작·재빌드 불필요).

섹터 파일은 **두 종류**다.

| 종류 | 위치 | 누가 쓰나 | 허브 배지 |
|---|---|---|---|
| **테마** (`vc:kind "theme"`, 기본값) | 최상위 `*.ttl` (bio.ttl 등) | 사람 — **손 편집 정본** | 테마 |
| **분류** (`vc:kind "taxonomy"`) | `generated/tx-<slug>.ttl` 12개 + `generated/tx-codes.json` | `scripts/valuechain/import_taxonomy.py` — **생성물, 편집 금지** (매 실행 덮어씀) | 분류 (자동 생성) |

| 파일 | 내용 |
|---|---|
| `core.ttl` | 스키마(클래스·술어 정의). 섹터 불문 1개. 보통 고칠 일 없음 |
| `catalog.ttl` | 섹터 허브(첫 화면)의 묶음·카드 목록. 묶음 = 분류 L1 12개, 묶음마다 첫 카드 = 분류 섹터, 이어서 테마 카드. 섹터 파일이 없는 카드는 "미작성"으로 보인다 |
| `bio.ttl` | 바이오 테마 섹터(첫 섹터, 헬스케어 묶음) |
| `*.ttl` | 그 외 파일 하나 = 테마 섹터 하나 |
| `generated/tx-*.ttl` | 분류 섹터(L1 하나 = 파일 하나). ⚠️고치지 않는다 — 원천을 고치고 다시 생성한다 |
| `generated/tx-codes.json` | L2 → 분류 코드(`F01` …). **추가 전용** — 새 L2 는 다음 번호, 있는 코드는 재번호하지 않는다. 생성기가 읽고 쓰는 상태라 `--check` 비교 대상 |

## 분류 섹터 갱신 (generated/)

원천은 Ongoings 「종목 분류체계」 폴더(읽기 전용 — 스크립트는 원천을 고치지 않는다).

```bash
export VC_TAXONOMY_SRC="$HOME/Library/CloudStorage/OneDrive-개인/Ongoings/종목 분류체계"   # 맥
# 윈도: set VC_TAXONOMY_SRC=C:\Users\adg01\OneDrive\Ongoings\종목 분류체계
.venv/bin/python scripts/valuechain/import_taxonomy.py --report   # 생성(덮어쓰기) + 요약
.venv/bin/python scripts/valuechain/import_taxonomy.py --check    # 쓰지 않고 비교 — 다르면 exit 1
.venv/bin/python scripts/valuechain/validate.py
```

- 입력: `outputs/Classfication.csv` · `work/universe_listings.jsonl` · `work/verified_batch_001.jsonl`(ISIN → 판정 근거·URL)
  · `work/ticker_changes.jsonl` · `work/taxonomy_registry.md`(L2 순서·정의).
- 매핑: L1 = 섹터(`tx-<slug>`), L2 = 대분류(코드 `tx-codes.json`), L1 만 있는 기업 = `{접두어}00` "L2 미확정",
  L3(후보 포함) = 카드 역할 줄(`vc:role`), 판정 근거 = 포인트, source_url = `vc:url`.
- 결정적: 같은 입력 → 바이트 동일 출력. 파일 헤더의 `vc-input sha256` 은 그 L1 입력만의 해시.
- 원천 CSV·universe 행 수가 다르거나 티커 정렬이 깨지면(원천이 쓰는 중) 아무것도 쓰지 않고 exit 1.
- 원천이 갱신되면 `apps/api/tests/test_valuechain.py` 의 L1별 멤버십 기대 수치도 함께 고친다.
- 손 보강(카드 문구 다듬기)은 후속 overlay(최상위 `tx-overlay-*.ttl`)로 할 예정 — **미구현**.

## 새 섹터 추가

1. `bio.ttl` 을 복사한다. 예: `cp bio.ttl semi.ttl`
2. 맨 위 `@prefix bio: <http://ge.local/valuechain/bio#>` 를 새 이름으로 바꾼다
   (예: `@prefix semi: <http://ge.local/valuechain/semi#>`), 파일 안 `bio:` 도 모두 바꾼다.
3. 섹터 노드의 `vc:code`(URL 에 쓰임, 예: `"semi"`)와 `rdfs:label` 을 바꾼다.
4. 분류·흐름·자료·논지·기업·멤버십 내용을 교체한다.
5. `catalog.ttl` 에 같은 `vc:code` 의 카드가 있는지 본다. 있으면 그 카드가 열리고,
   없으면 허브의 "미분류" 묶음에 보인다 — 카드 한 줄을 추가해 묶음에 넣는다.
6. 검증한다(아래). 코드는 고치지 않는다.

기업 노드(`co:`)는 섹터와 무관하다 — 다른 섹터 파일에 이미 있는 기업이면 같은 IRI
(`co:US-NVDA`)를 그대로 쓰고, 섹터별 내용은 멤버십 노드에 쓴다.
**같은 IRI 는 모든 파일에서 `vc:ticker`·`vc:country` 가 같아야 하고, 하나의 (ticker, country) 는
IRI 하나에만 대응한다**(validate 가 검사 — `co:US-BRK-B` 와 `co:US-BRK.B` 공존 금지; 클래스주는 점 표기 `BRK.B`).
라벨은 파일별 관점이라 달라도 된다 — bio 와 분류 파일이 공유하는 기업(35개)은 bio 에서 기존 @ko 이름을,
분류 파일은 정제된 영문 이름(무태그)을 쓴다.

## 술어 요약

관계는 **한 방향만** 쓴다. 역방향(`vc:contains`·`vc:hasSubCategory`·`vc:composedOf`)은
로더가 만든다 — 파일에 쓰지 않는다.

| 대상 | 술어 | 값 |
|---|---|---|
| 섹터 | `vc:code` · `rdfs:label "…"@ko , "…"@en` · `rdfs:comment` | |
| 섹터 | `vc:kind` | 선택. `"theme"`(기본) · `"taxonomy"`(생성물) |
| 분류 | `vc:subCategoryOf` | 상위 분류, 최상위는 섹터 노드 (정확히 1개) |
| 분류 | `vc:code` (섹터 안 유일) · `vc:order` · `rdfs:label @ko` · `rdfs:comment @ko` | |
| 분류 | `vc:shortLabel` · `vc:color "#rrggbb"` (없으면 상위 색) · `vc:marketSize` | 선택 |
| 분류 | `vc:feedsInto` | 다음 단계 분류 |
| 기업 `co:{국가}-{티커}` | `rdfs:label @ko(/@en)` · `vc:ticker` · `vc:exchange` · `vc:country` · `vc:listed true` | |
| 비상장 `co:{국가}-x-{slug}` | `vc:listed false`, 티커·거래소 없음 | |
| 기업 | `vc:otherCountry` | 선택, 복수 가능 |
| 기업 | `vc:isin` | 선택(분류 생성물이 기록 — 티커 변경에도 안정적인 키) |
| 멤버십 `{섹터}:m-{기업 로컬명}` | `vc:company` · `vc:sector` | |
| 멤버십 | `vc:belongsTo` (≥1) · `vc:primaryCategory` (belongsTo 중 하나 = 카드 위치) | |
| 멤버십 | `vc:role` · `vc:points ( "…" "…" )` (순서 유지) · `vc:source` | |
| 멤버십 | `vc:url "…"^^xsd:anyURI` | 선택. 판정 근거 링크 |
| 자료 | `vc:code`(화면 태그) · `rdfs:label`(파일) · `rdfs:comment`(비고) · `vc:order` | |
| 논지 | `rdfs:label`(출처 표기) · `rdfs:comment`(본문) · `vc:order` | |

## 검증

```bash
.venv/bin/python scripts/valuechain/validate.py
```

파싱 오류, 분류 코드 중복, 고아·순환 분류, 없는 `feedsInto`·`belongsTo`·`source` 대상,
소속 없는 멤버십, `primaryCategory ∉ belongsTo`, 잘못된 `vc:kind`, 파일 간 기업 신원 불일치
(같은 IRI 의 ticker·country 차이, 같은 ticker·country 의 IRI 둘)를 잡는다. `OK` 가 나와야 한다.

⚠️API 는 GZip 압축(`main.py` `GZipMiddleware`)을 쓴다 — 분류 섹터 응답이 수백 KB 라서. 전 응답에 걸리므로
나중에 스트리밍(SSE) 엔드포인트를 추가하면 그 경로는 압축에서 빼야 한다.
