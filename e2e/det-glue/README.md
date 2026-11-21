# det arm 고정 glue

결정적 생성 arm(`det`)이 쓰는 step 정의다. `td.detgen.render`가 generation마다 이 디렉터리를 `glue/support/`로 복사한다.

- `e2e/harness/CONTRACT.md`의 "feature마다 Steps 클래스" 규약에 대한 det 전용 예외다. det는 feature별 Steps 클래스를 만들지 않고 모든 step을 `glue/support/`에 둔다. `td.scenarios.layout_violations`는 `glue/support/` 아래 배치를 허용하므로 그대로 통과한다.
- 이 예외를 CONTRACT.md에 적지 않는 이유: CONTRACT.md는 LLM arm(base/jqa/owl)의 생성 입력 번들에 들어간다. 내용을 바꾸면 기존 arm의 번들 해시가 바뀌어 스냅샷을 재사용할 수 없다(REQ-102).
- 하네스 API(`Harness.baseUrl/authed/anonymous`)와 허용 의존성(Cucumber 8.1.0, REST Assured 5.5.1, AssertJ)만 쓰고 `@Before`/`@After` 훅은 두지 않는다.
