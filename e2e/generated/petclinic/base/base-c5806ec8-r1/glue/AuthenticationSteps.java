package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.HashMap;
import java.util.Map;
import td.harness.Harness;

public class AuthenticationSteps {

    private Response lastResponse;

    @When("a login is attempted with variant {word}")
    public void attemptLogin(String variant) {
        String s = ApiSupport.suffix();
        if ("unknown-user".equals(variant)) {
            Map<String, Object> body = new HashMap<>();
            body.put("username", "nouser_" + s);
            body.put("password", "wrong_" + s);
            lastResponse = Harness.anonymous().contentType("application/json").body(body).post("/api/auth/login");
        } else if ("empty-body".equals(variant)) {
            lastResponse = Harness.anonymous().contentType("application/json").body("{}").post("/api/auth/login");
        } else {
            throw new IllegalArgumentException("Unknown login variant: " + variant);
        }
    }

    @Then("the login attempt is rejected with a client error")
    public void loginRejected() {
        assertThat(lastResponse.statusCode()).as("body: %s", lastResponse.asString()).isBetween(400, 499);
    }

    @When("a malformed token is submitted for validation")
    public void submitMalformedToken() {
        String token = "malformed." + ApiSupport.suffix() + ".token";
        Map<String, Object> body = new HashMap<>();
        body.put("token", token);
        lastResponse = Harness.anonymous()
                .header("Authorization", "Bearer " + token)
                .contentType("application/json")
                .body(body)
                .post("/api/auth/validate");
    }

    @Then("the malformed token is not reported as valid")
    public void tokenNotValid() {
        int status = lastResponse.statusCode();
        String raw = lastResponse.asString();
        String body = raw == null ? "" : raw;
        boolean rejected = status >= 400 && status < 500;
        boolean reportedInvalid = status >= 200 && status < 300 && !body.toLowerCase().contains("true");
        assertThat(rejected || reportedInvalid).as("status %s body %s", status, body).isTrue();
    }
}
