package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

public class ApiAccessControlSteps {

    private Response response;

    @When("an anonymous client sends {word} to {string}")
    public void anAnonymousClientSendsTo(String method, String path) {
        if ("POST".equalsIgnoreCase(method)) {
            response = Harness.anonymous().contentType("application/json")
                    .body(ApiSupport.uniqueReservationBody(1)).post(path);
        } else {
            response = Harness.anonymous().get(path);
        }
    }

    @Then("the anonymous request is denied")
    public void theAnonymousRequestIsDenied() {
        assertThat(response.statusCode()).as("response: " + response.asString()).isIn(401, 403);
    }
}
