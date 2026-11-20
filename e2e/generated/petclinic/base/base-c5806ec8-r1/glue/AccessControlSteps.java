package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.Map;
import td.harness.Harness;

public class AccessControlSteps {

    private Response lastResponse;

    @When("an anonymous client sends {word} to {word}")
    public void anonymousRequest(String method, String path) {
        if ("GET".equalsIgnoreCase(method)) {
            lastResponse = Harness.anonymous().get(path);
        } else if ("POST".equalsIgnoreCase(method)) {
            Map<String, Object> body = ApiSupport.randomReservationBody(2);
            lastResponse = Harness.anonymous().contentType("application/json").body(body).post(path);
        } else {
            throw new IllegalArgumentException("Unsupported method: " + method);
        }
    }

    @Then("the anonymous request is refused as unauthenticated")
    public void refused() {
        assertThat(lastResponse.statusCode()).as("body: %s", lastResponse.asString()).isIn(401, 403);
    }
}
