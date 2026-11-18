package td.minisut.api;

import java.util.Map;

import io.restassured.RestAssured;
import io.restassured.http.ContentType;
import io.restassured.specification.RequestSpecification;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.extension.ExtendWith;

import static io.restassured.RestAssured.given;

/** out-of-process 블랙박스 테스트 공통부. 실행 중인 mini-sut에 HTTP로만 접근한다(-Dminisut.base-url). */
@Tag("blackbox")
@ExtendWith(PerTestCoverageExtension.class)
abstract class ApiBlackBoxTestSupport {

    static final String USERNAME = System.getenv().getOrDefault("TD_SUT_USER", "admin");
    static final String PASSWORD = System.getenv().getOrDefault("TD_SUT_PASS", "password");

    private static volatile String cachedToken;

    static {
        RestAssured.baseURI = System.getProperty("minisut.base-url", "http://localhost:8080");
        RestAssured.enableLoggingOfRequestAndResponseIfValidationFails();
    }

    static String login(String username, String password) {
        return given().contentType(ContentType.JSON)
            .body(Map.of("username", username, "password", password))
            .when().post("/api/auth/login")
            .then().statusCode(200)
            .extract().path("token");
    }

    static String authToken() {
        String token = cachedToken;
        if (token == null) {
            synchronized (ApiBlackBoxTestSupport.class) {
                token = cachedToken;
                if (token == null) {
                    token = cachedToken = login(USERNAME, PASSWORD);
                }
            }
        }
        return token;
    }

    RequestSpecification authenticated() {
        return given().header("Authorization", "Bearer " + authToken()).contentType(ContentType.JSON);
    }
}
