package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.Map;
import td.harness.Harness;

public class ReservationListingSteps {

    private Response lastResponse;
    private String createdPetName;

    @Given("a boarding reservation with {int} nights has been created for listing")
    public void createForListing(int nights) {
        Map<String, Object> body = ApiSupport.randomReservationBody(nights);
        createdPetName = String.valueOf(body.get("petName"));
        Response response = Harness.authed().contentType("application/json").body(body).post("/api/reservations");
        assertThat(response.statusCode()).as("create status, body: %s", response.asString()).isBetween(200, 299);
    }

    @When("the client lists boarding reservations")
    public void listAll() {
        lastResponse = Harness.authed().get("/api/reservations");
    }

    @When("the client lists boarding reservations with query parameter {word} set to {word}")
    public void listWithParam(String name, String value) {
        lastResponse = Harness.authed().queryParam(name, value).get("/api/reservations");
    }

    @Then("the reservation listing response has status {int}")
    public void hasStatus(int status) {
        assertThat(lastResponse.statusCode()).as("body: %s", lastResponse.asString()).isEqualTo(status);
    }

    @Then("the reservation listing contains the created reservation")
    public void containsCreated() {
        assertThat(lastResponse.asString()).contains(createdPetName);
    }
}
