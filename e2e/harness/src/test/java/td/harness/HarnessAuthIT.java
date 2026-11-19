package td.harness;

import static org.assertj.core.api.Assertions.assertThat;

import io.restassured.specification.RequestSpecification;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;

/**
 * REQ-026: 실제 SUT에 대해 authed()는 probe가 2xx이고 anonymous()는 unauthenticated_status다.
 * 속성(td.base-url, td.control-url, td.auth.login/user/pass, td.auth.probe, td.auth.unauthenticated-status)은
 * pytest 래퍼(test_req026_auth_harness)가 SUT 기동 뒤에 넘긴다.
 */
class HarnessAuthIT {

    private static String property(String key) {
        String value = System.getProperty(key);
        assertThat(value).as("시스템 속성 " + key).isNotBlank();
        return value;
    }

    private static String probePath() {
        String[] parts = property("td.auth.probe").split(" ", 2);
        assertThat(parts[0]).isEqualTo("GET");
        return parts[1];
    }

    @Test
    void authedProbeIsSuccessful() {
        int status = Harness.authed().get(probePath()).statusCode();
        assertThat(status).isBetween(200, 299);
    }

    @Test
    void anonymousProbeReturnsTheDescriptorStatus() {
        int expected = Integer.parseInt(property("td.auth.unauthenticated-status"));
        assertThat(Harness.anonymous().get(probePath()).statusCode()).isEqualTo(expected);
    }

    @Test
    void authedSendsBearerAndAnonymousSendsNoAuthorization() {
        AtomicReference<String> authedHeader = new AtomicReference<>();
        AtomicReference<String> anonymousHeader = new AtomicReference<>("<unset>");
        capture(Harness.authed(), authedHeader).get(probePath());
        capture(Harness.anonymous(), anonymousHeader).get(probePath());
        assertThat(authedHeader.get()).startsWith("Bearer ").hasSizeGreaterThan("Bearer ".length());
        assertThat(anonymousHeader.get()).isNull();
    }

    @Test
    void loginHappensOnceForTheWholeSuite() {
        Harness.authed().get(probePath());
        Harness.authed().get(probePath());
        Harness.authed().get(probePath());
        assertThat(AuthSession.loginCount()).isEqualTo(1);
    }

    @Test
    void baseUrlComesFromTheSystemProperty() {
        assertThat(Harness.baseUrl()).isEqualTo(property("td.base-url"));
    }

    private static RequestSpecification capture(RequestSpecification spec, AtomicReference<String> header) {
        return spec.filter((request, response, context) -> {
            header.set(request.getHeaders().hasHeaderWithName("Authorization")
                    ? request.getHeaders().getValue("Authorization") : null);
            return context.next(request, response);
        });
    }
}
