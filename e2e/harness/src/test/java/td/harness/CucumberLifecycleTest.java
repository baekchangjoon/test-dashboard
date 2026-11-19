package td.harness;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.platform.engine.discovery.DiscoverySelectors.selectClasspathResource;

import com.sun.net.httpserver.HttpServer;
import io.restassured.path.json.JsonPath;
import java.net.InetSocketAddress;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.platform.launcher.EngineFilter;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;

/** 진짜 Cucumber 엔진으로 훅 연결을 확인한다: Scenario.getUri/getLine이 testids.json과 맞는지, Outline 행이 행 줄로 기록되는지. */
class CucumberLifecycleTest {

    private HttpServer server;
    private Path results;
    private Path testIds;

    @BeforeEach
    void setUp(@TempDir Path dir) throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            exchange.sendResponseHeaders(204, -1);
            exchange.close();
        });
        server.start();
        String url = "http://127.0.0.1:" + server.getAddress().getPort();
        results = dir.resolve("scenario-results.json");
        testIds = dir.resolve("testids.json");
        Files.writeString(testIds, "{\"arm\":\"base\",\"inputHash\":\"0123456789abcdef\",\"rep\":1,\"gen\":null,\"features\":["
                + "{\"path\":\"td/harness/lifecycle.feature\",\"name\":\"Lifecycle sample\",\"pickles\":["
                + "{\"line\":3,\"name\":\"plain hit\"},{\"line\":12,\"name\":\"row <n>\"},{\"line\":13,\"name\":\"row <n>\"},"
                + "{\"line\":15,\"name\":\"no requests\"},{\"line\":18,\"name\":\"undefined\"}]}]}");
        System.setProperty("td.base-url", url);
        System.setProperty("td.control-url", url);
        System.setProperty("td.results", results.toString());
        System.setProperty("td.testids", testIds.toString());
    }

    @AfterEach
    void tearDown() {
        server.stop(0);
        for (String key : new String[] {"td.base-url", "td.control-url", "td.results", "td.testids", "pjacoco.control-url"}) {
            System.clearProperty(key);
        }
    }

    @Test
    void realCucumberRunWritesOneLinePerPickleWithTheDryRunLines() throws Exception {
        var request = LauncherDiscoveryRequestBuilder.request()
                .selectors(selectClasspathResource("td/harness/lifecycle.feature"))
                .filters(EngineFilter.includeEngines("cucumber"))
                .configurationParameter("cucumber.glue", "td.harness")
                .configurationParameter("cucumber.publish.quiet", "true")
                .build();
        var listener = new SummaryGeneratingListener();
        LauncherFactory.create().execute(request, listener);

        List<Map<String, Object>> lines = new ArrayList<>();
        for (String line : Files.readAllLines(results)) {
            lines.add(JsonPath.from(line).getMap(""));
        }
        assertThat(lines).extracting(line -> line.get("testId")).containsExactly(
                "E2E_base_01234567r1_Lifecycle_sample#L3", "E2E_base_01234567r1_Lifecycle_sample#L12",
                "E2E_base_01234567r1_Lifecycle_sample#L13", "E2E_base_01234567r1_Lifecycle_sample#L15",
                "E2E_base_01234567r1_Lifecycle_sample#L18");
        assertThat(lines).extracting(line -> line.get("status"))
                .containsExactly("passed", "passed", "passed", "passed", "undefined");
        assertThat(lines).extracting(line -> line.get("requests")).containsExactly(1, 1, 1, 0, 0);
        assertThat(lines.get(0).get("exec")).isEqualTo("exec/E2E_base_01234567r1_Lifecycle_sample#L3.exec");
        assertThat(lines.get(3).get("exec")).isNull();
    }
}
