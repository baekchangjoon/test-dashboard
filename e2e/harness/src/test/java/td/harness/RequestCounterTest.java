package td.harness;

import static org.assertj.core.api.Assertions.assertThat;

import com.sun.net.httpserver.HttpServer;
import io.pjacoco.testkit.Pjacoco;
import io.restassured.RestAssured;
import java.net.InetSocketAddress;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class RequestCounterTest {

    private HttpServer server;
    private String baseUrl;

    @BeforeEach
    void startServer() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/ping", exchange -> {
            exchange.sendResponseHeaders(204, -1);
            exchange.close();
        });
        server.start();
        baseUrl = "http://127.0.0.1:" + server.getAddress().getPort();
    }

    @AfterEach
    void stopServer() {
        server.stop(0);
        Pjacoco.clearCurrentTestId();
        RequestCounter.reset("T1");
        RequestCounter.reset("T2");
    }

    private void ping() {
        Harness.install(); // 전역 필터(다른 테스트 클래스가 먼저 설치했을 수도 있다: 멱등)
        RestAssured.given().baseUri(baseUrl).get("/ping").then().statusCode(204);
    }

    @Test
    void countsOnlyWhileATestIdIsActiveAndPerTestId() {
        ping(); // testId 없음: 센 것이 없어야 한다(로그인 같은 스위트 수준 호출)
        assertThat(RequestCounter.count("T1")).isZero();
        Pjacoco.setCurrentTestId("T1");
        ping();
        ping();
        Pjacoco.setCurrentTestId("T2");
        ping();
        assertThat(RequestCounter.count("T1")).isEqualTo(2);
        assertThat(RequestCounter.count("T2")).isEqualTo(1);
    }

    @Test
    void takeReturnsTheCountAndClearsIt() {
        Pjacoco.setCurrentTestId("T1");
        ping();
        assertThat(RequestCounter.take("T1")).isEqualTo(1);
        assertThat(RequestCounter.take("T1")).isZero();
    }

    @Test
    void threadsStartedByTheTestStayAttributedToIt() throws Exception {
        Pjacoco.setCurrentTestId("T1");
        AtomicReference<Throwable> failure = new AtomicReference<>();
        Thread worker = new Thread(() -> {
            try {
                ping();
            } catch (Throwable error) {
                failure.set(error);
            }
        });
        worker.start();
        worker.join();
        assertThat(failure.get()).isNull();
        assertThat(RequestCounter.count("T1")).isEqualTo(1);
    }

    @Test
    void requestsThatFailToConnectAreNotCounted() {
        Pjacoco.setCurrentTestId("T1");
        server.stop(0);
        try {
            Harness.install();
            RestAssured.given().baseUri(baseUrl).get("/ping");
        } catch (Exception expected) {
            // 연결 실패: SUT에 닿지 않았으므로 세지 않는다
        }
        assertThat(RequestCounter.count("T1")).isZero();
    }
}
