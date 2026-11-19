package td.harness;

import groovy.json.JsonOutput;
import io.restassured.path.json.JsonPath;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 스위트당 한 번 로그인해 토큰을 들고 있다. 엔드포인트는 서술자가 주는 {@code td.auth.login}("METHOD /path"),
 * 자격 증명은 {@code td.auth.user}/{@code td.auth.pass}다. 토큰 필드 이름은 {@code td.auth.token-field}(기본 token).
 * 로그인은 REST Assured가 아니라 JDK HttpClient로 보낸다: 전역 필터가 시나리오의 요청 수에 이 호출을 섞지 않게 하기 위해서다.
 */
final class AuthSession {

    private static final Object LOCK = new Object();
    private static volatile String token;
    private static int logins;

    private AuthSession() {
    }

    static String token() {
        String current = token;
        if (current == null) {
            synchronized (LOCK) {
                current = token;
                if (current == null) {
                    current = token = login();
                    logins++;
                }
            }
        }
        return current;
    }

    /** 이 JVM에서 실제로 로그인한 횟수(테스트용). */
    static int loginCount() {
        synchronized (LOCK) {
            return logins;
        }
    }

    /** 테스트용: 다음 요청에서 다시 로그인한다. */
    static void forget() {
        synchronized (LOCK) {
            token = null;
            logins = 0;
        }
    }

    private static String required(String key) {
        String value = System.getProperty(key);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException("시스템 속성 " + key + "가 필요하다");
        }
        return value;
    }

    private static String login() {
        String[] parts = required("td.auth.login").split(" ", 2);
        if (parts.length != 2 || parts[1].isBlank()) {
            throw new IllegalStateException("td.auth.login은 'METHOD /path' 형식이어야 한다: " + parts[0]);
        }
        Map<String, String> credentials = new LinkedHashMap<>();
        credentials.put("username", required("td.auth.user"));
        credentials.put("password", required("td.auth.pass"));
        String body = JsonOutput.toJson(credentials);
        HttpRequest request = HttpRequest.newBuilder(URI.create(Harness.baseUrl() + parts[1].trim()))
                .timeout(Duration.ofSeconds(30))
                .header("Content-Type", "application/json")
                .method(parts[0], HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8))
                .build();
        HttpResponse<String> response;
        try {
            response = HttpClient.newHttpClient().send(request, HttpResponse.BodyHandlers.ofString());
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("로그인 중 중단됐다", interrupted);
        } catch (java.io.IOException failure) {
            throw new IllegalStateException("로그인 요청이 실패했다: " + failure, failure);
        }
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new IllegalStateException("로그인이 2xx가 아니다: HTTP " + response.statusCode());
        }
        String field = System.getProperty("td.auth.token-field", "token");
        String value = JsonPath.from(response.body()).getString(field);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException("로그인 응답에 '" + field + "' 필드가 없다");
        }
        return value;
    }
}
