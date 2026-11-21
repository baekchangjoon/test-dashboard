# controlled fixture (Task 4, REQ-109·REQ-107)

모든 값이 번들 안에서 해결되는 합성 det 번들이다. 실제 SUT와 무관한 이름(`ex.shop.*`, `/svc/*`)만 쓴다.
테스트는 이 디렉터리의 6개 JSON을 읽어 STAMP를 붙인 번들로 쓴 뒤(`_make_bundle`) `derive`를 돌린다.

## 구성

- 엔드포인트(api = `/svc/**`, 뷰 `GET /home` 제외): `POST /svc/orders`(본문 `OrderForm` 7필드), `GET /svc/orders/{orderId}`(query `limit`),
  `POST /svc/session`(하네스 로그인, 본문 `Credentials`), `GET /svc/catalog`(계획 없음, 그래프 전용).
- 계획 `OrderService.place`: 빈 본문, 범위(`quantity`, `bay`), null+길이(`label`), enum 결합(`tone == NEON && credit < 50`),
  null+날짜(`shipDate`), equals 분기(`"FREESHIP".equals(voucher)`), count(`countByBay(bay) >= BAY_LIMIT`, 상수 2).
- 계획 `OrderService.fetch`: id 미존재(no_data), query 위반(`limit > 100`).
- 예외 상태(그래프): Invalid=422(bbtg는 400), Clash=409, Missing=404(같은 컨트롤러 핸들러).
- key-params의 BRANCH_CONDITION은 공백만 다른 중복이라 보충 항목이 생기지 않는다.

## 기대 케이스(`expected-cases.json`, 35건) 손 계산

| 엔드포인트 | 규칙 | 건수 | 근거 |
|---|---|---|---|
| POST /svc/orders | empty-body | 1 | `form = null/empty` |
| | violation / valid-boundary | 2 / 2 | quantity `<1`→0·1, `>9`→10·9 |
| | | 2 / 2 | label `==null`→null·baseline, `length>12`→13자·12자 |
| | | 1 / 2 | `NEON && credit<50` → {NEON,49}; 경계 {MATTE,49}, {NEON,50} |
| | | 3 / 2 | shipDate `==null`→null·today+1, `!isAfter(now)`→today, today-1 · today+1 |
| | | 1 / 1 | count ≥ 2 → 선행 2건 + 1 / 선행 1건 + 1 |
| | | 2 / 2 | bay `<10`→9·10, `>20`→21·20 |
| | branch-entry | 1 | voucher=FREESHIP, status-only |
| | baseline-valid | 1 | quantity 1, label 12자, tone MATTE, credit 50, shipDate today+1, voucher uniq, bay 분산 |
| | enum-value | 2 | baseline 상수(MATTE) 밖의 GLOSS, NEON |
| | auth | 1 | 하네스 403 |
| GET /svc/orders/{orderId} | no-data | 1 | orderId=1000000, 기대 404(그래프) |
| | violation / valid-boundary | 1 / 1 | limit 101 / 100 (선행 생성 + `{orderId}`→응답 `id`) |
| | baseline-valid | 1 | limit 100 |
| | auth | 1 | |
| GET /svc/catalog | happy / auth | 1 / 1 | 그래프 전용 GET |
| POST /svc/session | — | 0 | 로그인이라 auth 없음, GET 아니라 happy 없음 |

합계 28 + 5 + 2 = 35. 생성 불가 0건이므로 `bySlot.total = generated = 35`.

분산(`bay`): 유효 범위 [10, 20]에서 경계값 {10, 20}을 빼면 11..19(9개)다. 값은 `11 + (sha256(caseId) mod 9)`이고 경계 집합 {9, 10, 20, 21}과 겹치지 않는다.

## 이론 모수(`universe.theoretical.value`) 손 계산 = **868**

필드별 동치 클래스 수 = 1(유효) + 그 필드 원자식 위반 클래스 수.

- POST /svc/orders: quantity 1+2, label 1+2, tone 1+1, credit 1+1, shipDate 1+2, voucher 1+1, bay 1+3(`<10`, `>20`, count)
  → 3 × 3 × 2 × 2 × 3 × 2 × 4 = **864**
- GET /svc/orders/{orderId}: orderId 1, limit 1+1 → **2**
- POST /svc/session: user 1, secret 1 → **1**
- GET /svc/catalog: 필드 없음 → **1**

합계 864 + 2 + 1 + 1 = **868**.
