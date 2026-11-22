# viz-kinds fixture (det-viz Task 2, REQ-201)

`controlled`와 같은 형식(6개 JSON, 테스트가 `_make_bundle`로 STAMP를 붙인다)의 합성 det 번들이다.
클래스 레지스트리의 kind 우선순위·필드 한정 id·적대적 문자열을 한 엔드포인트에서 확인하려고 만들었다.
실제 SUT와 무관한 이름(`ex.kinds.*`, `/vk/*`)만 쓴다.

## 구성

- 엔드포인트: `POST /vk/items`(본문 `ItemForm` 5필드 + 이름 없는 query 파라미터 1개), `GET /vk/ping`(요청 필드 없음 → `fields: []`).
- query 파라미터는 key-params `http_name: "q"`로 이름을 얻는다. 본문에도 `q`가 있어 `body.q`와 `query.q`가 같은 이름이다.
- 계획 `ItemService.put` 항목과 의도:

| index | 조건식 | 기대 | 의도 |
|---|---|---|---|
| 0 | `form.qty() < 1 \|\| form.qty() > 99` | 400 | 오류 항목. `\|\|`·`<`가 든 원문 |
| 1 | `form.qty() < 1` | 분기 | 0번과 같은 키 `<1` → kind `violation`(오류가 이김) |
| 2 | `form.qty() > 50` | 분기 | 분기 전용 키 → kind `branch` |
| 3 | `repository.countBySlot(form.slot()) >= SLOT_LIMIT` | 400 | count(상수 3) → kind `count`, 라벨 `count ≥ 3` |
| 4 | `form.code().length() > maxLen` | 400 | 미변환 원자식(지역 변수) → kind `raw`, 라벨 `length > maxLen` |
| 5 | `"</script><img onerror=x>".equals(form.code())` | 400 | 적대적 문자열 라벨·원문 복원 |
| 6 | `form.note() != null` | 400 | 7번과 모순 쌍의 X → kind `contradicted`, 라벨 `!= null` |
| 7 | `form.note().length() < 2 \|\| form.note().length() > 10` | 400 | 모순 쌍의 Y(경계값이 모두 6번을 참으로 만든다) |
| 8 | `form.q() == null` | 400 | 필드 매칭은 이름 기준이라 `body.q`·`query.q` 둘 다 `== null` 클래스를 가진다. id는 `loc.name`으로 갈린다 |

## 클래스 수(valid 포함)

`body.code` 3, `body.note` 4, `body.q` 2, `body.qty` 4, `body.slot` 2, `query.q` 2.
