package td.harness;

import static org.assertj.core.api.Assertions.assertThat;

import com.sun.net.httpserver.HttpServer;
import io.cucumber.java.Status;
import io.restassured.path.json.JsonPath;
import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/** 가짜 SUT/제어 서버로 수명주기(start -> 요청 -> stop -> NDJSON 한 줄)를 검증한다. */
class CoverageHooksTest {

    private HttpServer server;
    private final List<String> controlCalls = new CopyOnWriteArrayList<>();
    private final List<String> baggageSeen = new CopyOnWriteArrayList<>();
    private Path results;
    private CoverageHooks hooks;

    @BeforeEach
    void setUp(@TempDir Path dir) throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/__coverage__/test", exchange -> {
            controlCalls.add(exchange.getRequestURI().getPath().substring("/__coverage__/test/".length()) + "?"
                    + URLDecoder.decode(exchange.getRequestURI().getRawQuery(), StandardCharsets.UTF_8));
            exchange.sendResponseHeaders(200, -1);
            exchange.close();
        });
        server.createContext("/api/ping", exchange -> {
            baggageSeen.add(String.valueOf(exchange.getRequestHeaders().getFirst("baggage")));
            exchange.sendResponseHeaders(204, -1);
            exchange.close();
        });
        server.start();
        String url = "http://127.0.0.1:" + server.getAddress().getPort();
        results = dir.resolve("S07").resolve("gen-1").resolve("scenario-results.json");
        System.setProperty("td.base-url", url);
        System.setProperty("td.control-url", url);
        System.setProperty("td.results", results.toString());
        hooks = new CoverageHooks();
    }

    @AfterEach
    void tearDown() {
        server.stop(0);
        for (String key : new String[] {"td.base-url", "td.control-url", "td.results", "pjacoco.control-url"}) {
            System.clearProperty(key);
        }
    }

    private void scenario(String testId, int requests, Status status) {
        hooks.begin(testId);
        for (int i = 0; i < requests; i++) {
            Harness.anonymous().get("/api/ping").then().statusCode(204);
        }
        hooks.finish(testId, status);
    }

    private List<Map<String, Object>> lines() throws Exception {
        List<Map<String, Object>> parsed = new ArrayList<>();
        for (String line : Files.readAllLines(results)) {
            parsed.add(JsonPath.from(line).getMap(""));
        }
        return parsed;
    }

    @Test
    void passedScenarioWithRequestsWritesOneLineWithExecPath() throws Exception {
        scenario("E2E_jqa_01234567r1_Owner#L5", 2, Status.PASSED);
        assertThat(controlCalls).containsExactly("start?testId=E2E_jqa_01234567r1_Owner#L5",
                "stop?testId=E2E_jqa_01234567r1_Owner#L5&result=passed");
        assertThat(baggageSeen).containsExactly("test.id=E2E_jqa_01234567r1_Owner#L5",
                "test.id=E2E_jqa_01234567r1_Owner#L5");
        assertThat(lines()).hasSize(1);
        Map<String, Object> line = lines().get(0);
        assertThat(line).containsOnlyKeys("testId", "status", "requests", "exec");
        assertThat(line.get("testId")).isEqualTo("E2E_jqa_01234567r1_Owner#L5");
        assertThat(line.get("status")).isEqualTo("passed");
        assertThat(line.get("requests")).isEqualTo(2);
        assertThat(line.get("exec")).isEqualTo("exec/E2E_jqa_01234567r1_Owner#L5.exec");
    }

    @Test
    void scenarioWithoutRequestsHasNullExec() throws Exception {
        scenario("E2E_jqa_01234567r1_Owner#L9", 0, Status.PASSED);
        Map<String, Object> line = lines().get(0);
        assertThat(line.get("requests")).isEqualTo(0);
        assertThat(line).containsKey("exec");
        assertThat(line.get("exec")).isNull();
        assertThat(Files.readString(results)).contains("\"exec\":null");
    }

    @Test
    void everyScenarioWritesExactlyOneStrictNdjsonLine() throws Exception {
        scenario("E2E_a_01234567r1_X#L1", 1, Status.PASSED);
        scenario("E2E_a_01234567r1_X#L2", 1, Status.FAILED);
        scenario("E2E_a_01234567r1_X#L3", 0, Status.UNDEFINED);
        String text = Files.readString(results);
        assertThat(text).endsWith("\n");
        assertThat(text.split("\n")).hasSize(3).allSatisfy(line -> assertThat(line).startsWith("{").endsWith("}"));
        assertThat(lines()).extracting(line -> line.get("status")).containsExactly("passed", "failed", "undefined");
    }

    @Test
    void undefinedAndOtherStatusesMapToContractValuesAndStopResult() throws Exception {
        assertThat(CoverageHooks.statusOf(Status.PASSED)).isEqualTo("passed");
        assertThat(CoverageHooks.statusOf(Status.UNDEFINED)).isEqualTo("undefined");
        for (Status other : new Status[] {Status.FAILED, Status.PENDING, Status.AMBIGUOUS, Status.SKIPPED}) {
            assertThat(CoverageHooks.statusOf(other)).isEqualTo("failed");
        }
        scenario("E2E_a_01234567r1_X#L3", 0, Status.UNDEFINED);
        assertThat(controlCalls.get(1)).endsWith("result=failed");
    }

    @Test
    void adapterChoiceIsRecordedInGenerationMetaNotInResults() throws Exception {
        scenario("E2E_a_01234567r1_X#L1", 1, Status.PASSED);
        scenario("E2E_a_01234567r1_X#L2", 1, Status.PASSED);
        Path meta = results.resolveSibling("generation-meta.json");
        assertThat(JsonPath.from(meta.toFile()).getString("coverageAdapter")).isEqualTo(CoverageHooks.COVERAGE_ADAPTER);
        assertThat(CoverageHooks.COVERAGE_ADAPTER).startsWith("pjacoco-testkit-restassured:");
        assertThat(Files.readString(results)).doesNotContain("coverageAdapter").doesNotContain(CoverageHooks.COVERAGE_ADAPTER);
    }

    @Test
    void existingGenerationMetaKeysSurviveTheAdapterRecord() throws Exception {
        Files.createDirectories(results.getParent());
        Files.writeString(results.resolveSibling("generation-meta.json"), "{\"genId\":\"jqa-01234567-r1\"}");
        scenario("E2E_a_01234567r1_X#L1", 1, Status.PASSED);
        JsonPath meta = JsonPath.from(results.resolveSibling("generation-meta.json").toFile());
        assertThat(meta.getString("genId")).isEqualTo("jqa-01234567-r1");
        assertThat(meta.getString("coverageAdapter")).isEqualTo(CoverageHooks.COVERAGE_ADAPTER);
    }

    @Test
    void controlPlaneFailureNeverBreaksTheScenario() throws Exception {
        System.setProperty("td.control-url", "http://127.0.0.1:1");
        scenario("E2E_a_01234567r1_X#L1", 1, Status.PASSED);
        assertThat(lines().get(0).get("requests")).isEqualTo(1);
    }
}
