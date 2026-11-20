package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiData;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.HashMap;
import java.util.Map;
import td.harness.Harness;

public class AuthenticationAndAccessSteps {

    private Response response;

    private String forgedToken() {
        return "forged." + ApiData.letters(24) + "." + ApiData.letters(16);
    }

    @When("an anonymous client sends a GET request to {string}")
    public void anonymousGet(String path) {
        response = Harness.anonymous().get(path);
    }

    @When("an anonymous client tries to book a boarding reservation")
    public void anonymousBooking() {
        Map<String, Object> body = ApiData.reservationBody(ApiData.uniqueName("Pet"), 2);
        response = Harness.anonymous().contentType("application/json").body(body).post("/api/reservations");
    }

    @When("a client with a forged bearer token sends a GET request to {string}")
    public void forgedTokenGet(String path) {
        response = Harness.anonymous().header("Authorization", "Bearer " + forgedToken()).get(path);
    }

    @When("a client logs in with a random unknown username")
    public void loginUnknownUser() {
        Map<String, Object> body = new HashMap<>();
        body.put("username", ApiData.uniqueName("nobody"));
        body.put("password", ApiData.letters(12));
        response = Harness.anonymous().contentType("application/json").body(body).post("/api/auth/login");
    }

    @When("a client asks the auth service to validate a forged token")
    public void validateForgedToken() {
        String token = forgedToken();
        Map<String, Object> body = new HashMap<>();
        body.put("token", token);
        response = Harness.anonymous().header("Authorization", "Bearer " + token)
                .contentType("application/json").body(body).post("/api/auth/validate");
    }

    @Then("the access attempt is refused as unauthenticated")
    public void accessRefused() {
        assertThat(response.statusCode()).as(response.asString()).isIn(401, 403);
    }

    @Then("the login attempt fails with a client error status")
    public void loginFails() {
        assertThat(response.statusCode()).as(response.asString()).isBetween(400, 499);
    }

    @Then("the forged token is not reported as valid")
    public void forgedTokenNotValid() {
        int code = response.statusCode();
        String compact = response.asString() == null ? "" : response.asString().replace(" ", "").toLowerCase();
        assertThat(code).as(response.asString()).isLessThan(500);
        boolean reportedValid = ApiData.isSuccess(code)
                && (compact.contains("valid\":true") || compact.equals("true"));
        assertThat(reportedValid).as(response.asString()).isFalse();
    }
}
