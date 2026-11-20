package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.LinkedHashMap;
import java.util.Map;
import td.harness.Harness;

public class AuthLoginSteps {

    private Response response;

    @When("a login is attempted with an unknown username")
    public void aLoginIsAttemptedWithAnUnknownUsername() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("username", "nouser" + ApiSupport.letters(10));
        body.put("password", "pw" + ApiSupport.letters(12));
        response = Harness.anonymous().contentType("application/json").body(body).post("/api/auth/login");
    }

    @When("a login is attempted with an empty body")
    public void aLoginIsAttemptedWithAnEmptyBody() {
        response = Harness.anonymous().contentType("application/json").body("{}").post("/api/auth/login");
    }

    @Then("the login attempt is rejected with a client error")
    public void theLoginAttemptIsRejectedWithAClientError() {
        assertThat(response.statusCode()).as("response: " + response.asString()).isBetween(400, 499);
    }
}
