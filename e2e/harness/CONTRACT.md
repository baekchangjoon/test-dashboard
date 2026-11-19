# E2E 하네스 계약

step 정의(Java, Cucumber)가 쓸 수 있는 하네스 API는 아래 세 가지뿐이다.
모든 메서드는 `td.harness.Harness`의 정적 메서드다.

```java
import td.harness.Harness;
```

| 메서드 | 반환 | 설명 |
|---|---|---|
| `Harness.baseUrl()` | `String` | 대상 서버의 base URL(스킴, 호스트, 포트). 경로는 포함하지 않는다. |
| `Harness.authed()` | REST Assured `RequestSpecification` | 인증된 요청 명세. base URL이 이미 설정돼 있다. |
| `Harness.anonymous()` | REST Assured `RequestSpecification` | 인증 헤더가 없는 요청 명세. base URL이 이미 설정돼 있다. |

## 사용 규칙

- 요청은 `Harness.authed().get("/경로")`처럼 보낸다. base URL을 step 코드에 직접 쓰지 않는다.
- 인증은 하네스가 처리한다. step 코드는 자격 증명을 알지 못하고 알 필요도 없다.
- 시나리오는 서로 독립이다. 시나리오가 필요한 데이터는 그 시나리오의 `Given` step이 API 호출로 직접 만든다.
  이미 들어 있는 데이터가 있다고 가정하지 않고, 다른 시나리오가 만든 데이터에 기대지 않는다.
- 데이터를 만들 때 값이 겹치지 않도록 시나리오마다 고유한 값을 쓴다(예: 시나리오 안에서 만든 난수 접미사).
- 시나리오가 만든 데이터를 정리하는 일은 요구하지 않는다. 서버는 generation마다 새로 뜬다.
- step 클래스는 feature별로 하나이고 `glue/<feature 파일 이름을 PascalCase로>Steps.java`에 둔다(예: `vet_lookup.feature` -> `glue/VetLookupSteps.java`). 클래스에는 `package` 선언이 있어야 하고, 하네스 이외의 의존성을 추가하지 않는다. 사용 가능한 라이브러리는
  Cucumber 8.1.0, REST Assured 5.5.1, AssertJ다.
- 시나리오 시작과 종료 처리(훅)는 하네스가 이미 갖고 있다. step 클래스에 `@Before`, `@After` 훅을 만들지 않는다.
- `@ignore`, `@Disabled`, `@wip` 같은 실행 제외 표식은 쓰지 않는다.
