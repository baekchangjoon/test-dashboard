package td.harness;

import groovy.json.JsonOutput;
import io.cucumber.java.After;
import io.cucumber.java.Before;
import io.cucumber.java.Scenario;
import io.cucumber.java.Status;
import io.pjacoco.testkit.Pjacoco;
import io.restassured.path.json.JsonPath;
import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 시나리오마다 testId를 정하고 커버리지 경계(start/stop)를 열고 닫은 뒤 {@code scenario-results.json}에 한 줄(NDJSON)을 쓴다.
 *
 * <p>커버리지 구현은 pjacoco testkit({@code pjacoco-testkit-restassured})이다. start/stop 호출과 baggage 헤더가 Cucumber 수명주기와
 * 맞고(활성 testId를 InheritableThreadLocal로 들고, 제어 호출 실패를 삼킨다) testId 형식(`#` 포함)도 그대로 쓸 수 있어서 직접
 * HTTP 어댑터를 두지 않았다. 선택 결과는 {@link #COVERAGE_ADAPTER}이고, 결과 파일이 아니라 같은 디렉터리의
 * {@code generation-meta.json}의 {@code coverageAdapter} 키에 기록한다.
 *
 * <p>속성: {@code td.control-url}(없거나 공백이면 start/stop 없이 요청만 세고 exec는 null), {@code td.testids}(S07이 만든 testids.json),
 * {@code td.results}(scenario-results.json 경로). {@code exec}는 결과 파일 기준 상대 경로 {@code exec/<testId>.exec}이다.
 */
public class CoverageHooks {

    public static final String COVERAGE_ADAPTER = "pjacoco-testkit-restassured:2.0.0";

    private static final Object WRITE_LOCK = new Object();
    private static volatile TestIds.Registry registry;
    private static volatile Path registrySource;

    private String currentTestId;

    @Before(order = 0)
    public void beforeScenario(Scenario scenario) {
        TestIds.Entry entry = lookup(scenario);
        currentTestId = entry != null ? entry.testId() : "UNMAPPED:" + scenario.getUri() + "#L" + scenario.getLine();
        begin(currentTestId);
        if (entry == null) {
            throw new IllegalStateException("td.testids에 없는 시나리오다: " + scenario.getUri() + ":" + scenario.getLine());
        }
    }

    @After(order = 10000)
    public void afterScenario(Scenario scenario) {
        finish(currentTestId, scenario.getStatus());
        currentTestId = null;
    }

    /** 경계 열기: 활성 testId 설정과 start 호출. 제어 호출 실패는 testkit이 삼킨다. */
    void begin(String testId) {
        Harness.install();
        String controlUrl = controlUrl();
        if (controlUrl != null) {
            System.setProperty("pjacoco.control-url", controlUrl);
        }
        // 로그인은 start 전에: 시나리오 안에서 일어나면 그 처리 코드가 이 시나리오의 droppedProbes로 잡힌다(AuthSession.prewarm).
        AuthSession.prewarm();
        RequestCounter.reset(testId);
        Pjacoco.setCurrentTestId(testId);
        if (controlUrl != null) {
            Pjacoco.start(testId, null);
        }
    }

    /** 제어 URL(없거나 공백이면 null): 없으면 start/stop 호출 없이 요청만 센다. */
    private static String controlUrl() {
        String value = System.getProperty("td.control-url");
        return value == null || value.isBlank() ? null : value;
    }

    /** 경계 닫기와 결과 한 줄 쓰기. */
    void finish(String testId, Status status) {
        String result = statusOf(status);
        boolean hasControl = controlUrl() != null;
        if (hasControl) {
            Pjacoco.stop(testId, "passed".equals(result) ? "passed" : "failed");
        }
        Pjacoco.clearCurrentTestId();
        int requests = RequestCounter.take(testId);
        Map<String, Object> line = new LinkedHashMap<>();
        line.put("testId", testId);
        line.put("status", result);
        line.put("requests", requests);
        // pjacoco는 커버 클래스가 0개인 스토어의 .exec를 쓰지 않는다: 요청이 없으면 .exec도 없다.
        line.put("exec", requests == 0 || !hasControl ? null : "exec/" + testId + ".exec");
        append(JsonOutput.toJson(line));
    }

    /** Cucumber 상태 -> 결과 계약 값. 통과와 undefined 외에는 모두 failed다. */
    static String statusOf(Status status) {
        if (status == Status.PASSED) {
            return "passed";
        }
        if (status == Status.UNDEFINED) {
            return "undefined";
        }
        return "failed";
    }

    private static Path resultsPath() {
        String value = System.getProperty("td.results");
        if (value == null || value.isBlank()) {
            throw new IllegalStateException("시스템 속성 td.results가 필요하다");
        }
        return Paths.get(value);
    }

    private static void append(String json) {
        Path results = resultsPath();
        synchronized (WRITE_LOCK) {
            try {
                Files.createDirectories(results.toAbsolutePath().getParent());
                Files.writeString(results, json + "\n", StandardCharsets.UTF_8, StandardOpenOption.CREATE,
                        StandardOpenOption.APPEND);
                recordAdapter(results.resolveSibling("generation-meta.json"));
            } catch (IOException failure) {
                throw new IllegalStateException("scenario-results.json에 쓰지 못했다: " + failure, failure);
            }
        }
    }

    /** 기존 키를 보존하면서 coverageAdapter만 기록한다. */
    private static void recordAdapter(Path meta) throws IOException {
        Map<String, Object> content = new LinkedHashMap<>();
        if (Files.isRegularFile(meta)) {
            Map<String, Object> existing = JsonPath.from(meta.toFile()).getMap("");
            if (existing != null) {
                content.putAll(existing);
            }
        }
        if (COVERAGE_ADAPTER.equals(content.get("coverageAdapter"))) {
            return;
        }
        content.put("coverageAdapter", COVERAGE_ADAPTER);
        Files.writeString(meta, JsonOutput.prettyPrint(JsonOutput.toJson(content)) + "\n", StandardCharsets.UTF_8);
    }

    private static TestIds.Entry lookup(Scenario scenario) {
        String value = System.getProperty("td.testids");
        if (value == null || value.isBlank()) {
            throw new IllegalStateException("시스템 속성 td.testids가 필요하다");
        }
        Path source = Paths.get(value);
        if (registry == null || !source.equals(registrySource)) {
            synchronized (WRITE_LOCK) {
                if (registry == null || !source.equals(registrySource)) {
                    registry = TestIds.Registry.load(source);
                    registrySource = source;
                }
            }
        }
        URI uri = scenario.getUri();
        return registry.lookup(uri.toString(), scenario.getLine());
    }
}
