package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiData;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.HashMap;
import java.util.Map;
import td.harness.Harness;

public class AccessControlSteps {

    private Response response;

    @When("an anonymous client sends GET to {string}")
    public void anAnonymousClientSendsGet(String path) {
        response = Harness.anonymous().get(path);
    }

    @When("an anonymous client submits a boarding reservation")
    public void anAnonymousClientSubmitsReservation() {
        response = Harness.anonymous().contentType("application/json").body(ApiData.reservationPayload())
                .post("/api/reservations");
    }

    @When("a client presenting the malformed bearer token {string} sends GET to {string}")
    public void aClientWithMalformedToken(String token, String path) {
        response = Harness.anonymous().header("Authorization", "Bearer " + token).get(path);
    }

    @When("an anonymous client logs in with a random unknown username and password")
    public void anAnonymousClientLogsInWithUnknownUser() {
        String s = ApiData.suffix();
        Map<String, Object> body = new HashMap<>();
        body.put("username", "ghost" + s);
        body.put("password", "wrong" + s);
        response = Harness.anonymous().contentType("application/json").body(body).post("/api/auth/login");
    }

    @When("an anonymous client posts an empty login body")
    public void anAnonymousClientPostsEmptyLogin() {
        response = Harness.anonymous().contentType("application/json").body("{}").post("/api/auth/login");
    }

    @When("an anonymous client asks to validate the garbage token {string}")
    public void anAnonymousClientValidatesGarbage(String token) {
        Map<String, Object> body = new HashMap<>();
        body.put("token", token);
        response = Harness.anonymous().contentType("application/json").body(body).post("/api/auth/validate");
    }

    @Then("the access control response status is 401 or 403")
    public void theStatusIs401Or403() {
        assertThat(response.statusCode()).as(ApiData.describe(response)).isIn(401, 403);
    }

    @Then("the login attempt is rejected with a client error")
    public void theLoginIsRejected() {
        assertThat(response.statusCode()).as(ApiData.describe(response)).isBetween(400, 499);
    }

    @Then("the token validation does not fail with a server error")
    public void theValidationDoesNotFail() {
        assertThat(response.statusCode()).as(ApiData.describe(response)).isLessThan(500);
    }
}
