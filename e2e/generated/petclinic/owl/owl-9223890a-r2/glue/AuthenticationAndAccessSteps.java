package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.HashMap;
import java.util.Map;
import td.harness.Harness;

public class AuthenticationAndAccessSteps {

    private static final String MALFORMED_TOKEN = "not.a.valid.token";

    private Response response;

    @When("an anonymous client sends GET to {string}")
    public void anonymousGet(String path) {
        response = Harness.anonymous().get(path);
    }

    @Then("the access control response status is 401 or 403")
    public void unauthorizedOrForbidden() {
        assertThat(response.statusCode()).as(response.asString()).isIn(401, 403);
    }

    @When("a client with a malformed bearer token sends GET to {string}")
    public void malformedTokenGet(String path) {
        response = Harness.anonymous().header("Authorization", "Bearer " + MALFORMED_TOKEN).get(path);
    }

    private Response login(String username, String password) {
        Map<String, Object> body = new HashMap<>();
        body.put("username", username);
        body.put("password", password);
        return Harness.anonymous().contentType("application/json").body(body).post("/api/auth/login");
    }

    @When("a login is attempted for an unknown username")
    public void loginUnknownUser() {
        response = login("nouser" + ApiSupport.randomLetters(10), "pw" + ApiSupport.randomLetters(12));
    }

    @When("a login is attempted for username {string} with a random wrong password")
    public void loginWrongPassword(String username) {
        response = login(username, "wrong" + ApiSupport.randomLetters(16));
    }

    @Then("the access control response is a client error")
    public void clientError() {
        assertThat(response.statusCode()).as(response.asString()).isBetween(400, 499);
    }

    @When("a malformed token is submitted for validation")
    public void validateMalformed() {
        Map<String, Object> body = new HashMap<>();
        body.put("token", MALFORMED_TOKEN);
        response = Harness.anonymous()
                .header("Authorization", "Bearer " + MALFORMED_TOKEN)
                .contentType("application/json")
                .body(body)
                .post("/api/auth/validate");
    }

    @Then("the validation response does not confirm the token")
    public void validationNotConfirmed() {
        int status = response.statusCode();
        if (status >= 200 && status < 300) {
            String compact = response.asString().replace(" ", "");
            assertThat(compact).doesNotContain("\"valid\":true");
            assertThat(compact).isNotEqualTo("true");
        } else {
            assertThat(status).as(response.asString()).isBetween(400, 499);
        }
    }
}
