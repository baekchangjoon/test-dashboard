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

    @When("a login is attempted for a randomly generated unknown username")
    public void aLoginIsAttemptedForAnUnknownUsername() {
        String s = ApiSupport.suffix();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("username", "nouser_" + s);
        body.put("password", "invalid-" + s);
        response = Harness.anonymous().contentType("application/json").body(ApiSupport.toJson(body))
                .post("/api/auth/login");
    }

    @When("a login is attempted with an empty request body")
    public void aLoginIsAttemptedWithAnEmptyRequestBody() {
        response = Harness.anonymous().contentType("application/json").body("{}").post("/api/auth/login");
    }

    @Then("the login attempt is rejected with a client error")
    public void theLoginAttemptIsRejectedWithAClientError() {
        assertThat(response.statusCode()).as("login: %s", response.asString()).isBetween(400, 499);
    }
}
