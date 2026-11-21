package glue.support;

import static org.assertj.core.api.Assertions.assertThat;

import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import io.restassured.specification.RequestSpecification;
import java.util.Arrays;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import td.harness.Harness;

/**
 * det arm의 모든 step(설계 §5.4). feature별 Steps 클래스를 만들지 않는 det 전용 예외라서 이 클래스 하나가 모든 det feature를 맡는다.
 *
 * <p>시나리오 상태는 인스턴스 필드에 둔다. Cucumber(DefaultObjectFactory)는 시나리오마다 새 인스턴스를 만든다.
 * 하네스 계약상 훅(@Before)을 쓸 수 없으므로 케이스 id는 시나리오 첫 step {@code Given the case "<id>"}로 받는다.
 * 본 요청의 응답을 받으면 {@code DET-STATUS <caseId> <code>} 한 줄을 표준 출력에 남긴다(선행 요청은 남기지 않는다).
 * 결과 집계는 이 줄로 class 기준 판정을 계산한다.
 */
public class DetSteps {

    private static final Pattern PATH_VARIABLE = Pattern.compile("\\{([^}/]+)}");
    private static final List<String> BODY_METHODS = Arrays.asList("POST", "PUT");
    private static final String JSON_TYPE = "application/json";

    private String caseId = "unknown";
    private String method;
    private String pathTemplate;
    private final Map<String, Object> pathVariables = new LinkedHashMap<>();
    private final Map<String, Object> queryParameters = new LinkedHashMap<>();
    private final Map<String, Object> bodyFields = new LinkedHashMap<>();
    private final Map<String, Object> variables = new HashMap<>();
    private boolean anonymous;
    private boolean noBody;
    private Response priorResponse;
    private int priorCount;
    private Response response;

    @Given("^the case \"([^\"]+)\"$")
    public void theCase(String id) {
        caseId = id;
    }

    @Given("^a prior request to \"([A-Z]+) ([^\"]+)\" with body (\\{.*\\})$")
    public void priorRequest(String priorMethod, String priorPath, String bodyJson) {
        sendPrior(priorMethod, priorPath, bodyJson);
    }

    @Given("^a prior request to \"([A-Z]+) ([^\"]+)\" with body (\\{.*\\}) capturing \"([^\"]+)\" as \"([^\"]+)\"$")
    public void priorRequestCapturing(String priorMethod, String priorPath, String bodyJson, String jsonField, String variable) {
        sendPrior(priorMethod, priorPath, bodyJson);
        capture(jsonField, variable);
    }

    @Given("^the prior response field \"([^\"]+)\" is captured as \"([^\"]+)\"$")
    public void capture(String jsonField, String variable) {
        assertThat(priorResponse).as("%s: 담을 선행 응답이 없다", caseId).isNotNull();
        Object captured = priorResponse.jsonPath().get(jsonField);
        assertThat(captured).as("%s: 선행 응답에 필드 %s가 없다", caseId, jsonField).isNotNull();
        variables.put(variable, captured);
    }

    @Given("^a request to \"([A-Z]+) ([^\"]+)\"$")
    public void aRequestTo(String requestMethod, String template) {
        method = requestMethod;
        pathTemplate = template;
    }

    @Given("^path variable \"([^\"]+)\" is (.+)$")
    public void pathVariable(String name, String literal) {
        pathVariables.put(name, DetValues.parse(literal));
    }

    @Given("^query parameter \"([^\"]+)\" is (.+)$")
    public void queryParameter(String name, String literal) {
        queryParameters.put(name, DetValues.parse(literal));
    }

    @Given("^body field \"([^\"]+)\" is (.+)$")
    public void bodyField(String name, String literal) {
        bodyFields.put(name, DetValues.parse(literal));
    }

    @Given("^the request is sent without authentication$")
    public void withoutAuthentication() {
        anonymous = true;
    }

    @Given("^the request has no body$")
    public void withoutBody() {
        noBody = true;
    }

    @When("^the request is sent$")
    public void send() {
        assertThat(method).as("%s: 요청 대상이 정해지지 않았다", caseId).isNotNull();
        RequestSpecification spec = anonymous ? Harness.anonymous() : Harness.authed();
        for (Map.Entry<String, Object> entry : pathVariables.entrySet()) {
            spec = spec.pathParam(entry.getKey(), DetValues.text(DetValues.resolve(entry.getValue(), variables)));
        }
        for (Map.Entry<String, Object> entry : queryParameters.entrySet()) {
            Object value = DetValues.resolve(entry.getValue(), variables);
            if (value != null) {  // null 쿼리 값은 파라미터를 보내지 않는다는 뜻이다
                spec = spec.queryParam(entry.getKey(), DetValues.text(value));
            }
        }
        if (noBody) {
            spec = spec.contentType(JSON_TYPE);
        } else if (!bodyFields.isEmpty() || BODY_METHODS.contains(method)) {
            spec = spec.contentType(JSON_TYPE).body(DetValues.toJson(DetValues.resolve(bodyFields, variables)));
        }
        response = spec.request(method, pathTemplate);
        System.out.println("DET-STATUS " + caseId + " " + response.statusCode());
    }

    @Then("^the response status is (\\d+)$")
    public void statusIs(int expected) {
        assertThat(response).as("%s: 응답이 없다", caseId).isNotNull();
        assertThat(response.statusCode()).as("%s 상태 코드", caseId).isEqualTo(expected);
    }

    @Then("^the response status is in class \"([1-5])xx\"$")
    public void statusClassIs(int expectedClass) {
        assertThat(response).as("%s: 응답이 없다", caseId).isNotNull();
        assertThat(response.statusCode() / 100).as("%s 상태 코드 class(실제 %d)", caseId, response.statusCode())
                .isEqualTo(expectedClass);
    }

    /** 선행 요청은 항상 인증된 요청이다. 경로의 {변수}는 앞선 선행 요청이 담은 변수로 채운다. 2xx가 아니면 시나리오를 멈춘다.
     * uniq 기호는 선행 요청 순번 salt로 풀어 본 요청·다른 선행 요청과 값이 겹치지 않게 한다. */
    private void sendPrior(String priorMethod, String priorPath, String bodyJson) {
        RequestSpecification spec = Harness.authed();
        Matcher matcher = PATH_VARIABLE.matcher(priorPath);
        while (matcher.find()) {
            String name = matcher.group(1);
            spec = spec.pathParam(name, DetValues.text(DetValues.resolve("ref:" + name, variables)));
        }
        Object body = DetValues.resolve(DetValues.parse(bodyJson), variables, "#prior" + priorCount++);
        priorResponse = spec.contentType(JSON_TYPE).body(DetValues.toJson(body)).request(priorMethod, priorPath);
        assertThat(priorResponse.statusCode() / 100).as("%s: 선행 요청 %s %s 실패(상태 %d)", caseId, priorMethod, priorPath,
                priorResponse.statusCode()).isEqualTo(2);
    }
}
