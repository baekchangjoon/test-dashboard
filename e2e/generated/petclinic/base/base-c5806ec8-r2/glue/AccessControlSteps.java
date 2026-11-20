package glue;

import glue.support.ApiSupport;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

import static org.assertj.core.api.Assertions.assertThat;

public class AccessControlSteps {

    private Response response;

    @When("an anonymous caller requests {string}")
    public void anonymousGet(String path) {
        response = Harness.anonymous().get(path);
    }

    @When("an anonymous caller submits a new reservation")
    public void anonymousCreate() {
        response = Harness.anonymous().contentType("application/json")
                .body(ApiSupport.uniqueReservationBody(2)).post("/api/reservations");
    }

    @Then("the anonymous request is refused as unauthenticated")
    public void refused() {
        assertThat(response.statusCode()).as("status, body: %s", response.asString()).isIn(401, 403);
    }
}
