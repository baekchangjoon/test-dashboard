package glue;

import glue.support.ApiSupport;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

public class AuthLoginSteps {

    private Response response;

    @When("a login is attempted for user {string} with a random wrong password")
    public void loginWithWrongPassword(String username) {
        attemptLogin(username, "wrong-" + ApiSupport.suffix());
    }

    @When("a login is attempted for a randomly named user that does not exist")
    public void loginUnknownUser() {
        attemptLogin("nouser" + ApiSupport.suffix(), "wrong-" + ApiSupport.suffix());
    }

    private void attemptLogin(String username, String password) {
        Map<String, Object> body = new HashMap<>();
        body.put("username", username);
        body.put("password", password);
        response = Harness.anonymous().contentType("application/json").body(body).post("/api/auth/login");
    }

    @Then("the login attempt is rejected with a client error")
    public void rejected() {
        assertThat(response.statusCode()).as("status, body: %s", response.asString()).isBetween(400, 499);
    }
}
