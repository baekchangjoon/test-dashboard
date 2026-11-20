package td.harness;

import static org.assertj.core.api.Assertions.assertThat;

import io.cucumber.java.Status;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.time.Duration;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestMethodOrder;

/**
 * 실제 SUT에서 하네스 경로(CoverageHooks + Harness.authed())의 per-test 귀속을 블랙박스 확장과 같은 직접 HTTP 경로와 비교한다.
 * 이 클래스는 요청만 보내고 경계를 연다. 판정(사이드카 JSON 비교)은 pytest 래퍼(test_e2e_coverage_attribution_matches_direct_path)가 한다.
 *
 * <p>순서가 의미를 가진다: {@link #harnessFirstScenario()}가 이 JVM의 첫 authed() 호출이다(로그인이 일어난다).
 * testId는 {@code ATTR_harness_first}, {@code ATTR_harness_second}, {@code ATTR_direct}로 고정이다.
 */
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class CoverageAttributionIT {

    static final String PATH = "/api/vets";

    @BeforeAll
    static void freshLogin() throws Exception {
        AuthSession.forget();
        System.setProperty("td.results", Files.createTempFile("attribution", ".ndjson").toString());
        assertThat(System.getProperty("td.control-url")).as("td.control-url").isNotBlank();
    }

    private static void harnessScenario(String testId) {
        CoverageHooks hooks = new CoverageHooks();
        hooks.begin(testId);
        int status = Harness.authed().get(PATH).statusCode();
        hooks.finish(testId, status == 200 ? Status.PASSED : Status.FAILED);
        assertThat(status).isEqualTo(200);
    }

    @Test
    @Order(1)
    void harnessFirstScenario() {
        harnessScenario("ATTR_harness_first");
    }

    @Test
    @Order(2)
    void harnessSecondScenario() {
        harnessScenario("ATTR_harness_second");
    }

    /** PerTestCoverageExtension과 같은 방식: 제어 엔드포인트 start/stop + baggage 헤더를 직접 보낸다(testkit 없음). */
    @Test
    @Order(3)
    void directControlPath() throws Exception {
        String testId = "ATTR_direct";
        String token = AuthSession.token();
        HttpClient client = HttpClient.newHttpClient();
        String control = System.getProperty("td.control-url").replaceAll("/+$", "");
        String encoded = URLEncoder.encode(testId, StandardCharsets.UTF_8);
        assertThat(post(client, control + "/__coverage__/test/start?testId=" + encoded)).isEqualTo(200);
        HttpRequest request = HttpRequest.newBuilder(URI.create(Harness.baseUrl() + PATH))
                .timeout(Duration.ofSeconds(30))
                .header("Authorization", "Bearer " + token)
                .header("baggage", "test.id=" + testId)
                .GET().build();
        int status = client.send(request, HttpResponse.BodyHandlers.discarding()).statusCode();
        assertThat(post(client, control + "/__coverage__/test/stop?testId=" + encoded + "&result=passed")).isEqualTo(200);
        assertThat(status).isEqualTo(200);
    }

    private static int post(HttpClient client, String url) throws Exception {
        HttpRequest request = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(30))
                .POST(HttpRequest.BodyPublishers.noBody()).build();
        return client.send(request, HttpResponse.BodyHandlers.discarding()).statusCode();
    }
}
