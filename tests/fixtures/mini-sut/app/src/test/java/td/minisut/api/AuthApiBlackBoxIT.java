package td.minisut.api;

import java.util.Map;

import io.restassured.http.ContentType;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.not;
import static org.hamcrest.Matchers.emptyOrNullString;

class AuthApiBlackBoxIT extends ApiBlackBoxTestSupport {

    @Test
    @DisplayName("POST /api/auth/login issues a bearer token")
    void loginIssuesBearerToken() {
        given().contentType(ContentType.JSON)
            .body(Map.of("username", USERNAME, "password", PASSWORD))
            .when().post("/api/auth/login")
            .then().statusCode(200).body("token", not(emptyOrNullString()));
    }
}
