package glue;

import glue.support.ApiSupport;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

public class AuthenticationSteps {

    private Response response;

    @When("a login is attempted with a random unknown username and password")
    public void loginWithUnknownUser() {
        Map<String, Object> body = new HashMap<>();
        body.put("username", "nouser" + ApiSupport.letters(10));
        body.put("password", "wrong" + ApiSupport.letters(10));
        response = Harness.authed().contentType("application/json").body(body).post("/api/auth/login");
    }

    @When("a login is attempted without a request body")
    public void loginWithoutBody() {
        response = Harness.authed().contentType("application/json").post("/api/auth/login");
    }

    @Then("the authentication response is a client error")
    public void authenticationClientError() {
        assertThat(response.statusCode()).as("response body: %s", response.asString()).isBetween(400, 499);
    }

    @When("a forged token is submitted to the token validation endpoint")
    public void submitForgedToken() {
        Map<String, Object> body = new HashMap<>();
        body.put("token", "forged." + ApiSupport.letters(12) + ".token");
        response = Harness.authed().contentType("application/json").body(body).post("/api/auth/validate");
    }

    @Then("the token validation does not report the token as valid")
    public void tokenNotValid() {
        int status = response.statusCode();
        assertThat(status).as("response body: %s", response.asString()).isBetween(200, 499);
        if (ApiSupport.isSuccess(status)) {
            Object valid = null;
            try {
                valid = response.jsonPath().get("valid");
            } catch (RuntimeException ignored) {
                valid = null;
            }
            assertThat(valid).isNotEqualTo(Boolean.TRUE);
        }
    }
}
