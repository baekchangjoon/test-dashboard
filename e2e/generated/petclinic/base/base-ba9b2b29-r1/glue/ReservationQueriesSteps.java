package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.Map;
import td.harness.Harness;

public class ReservationQueriesSteps {

    private Map<String, Object> created;
    private Response response;

    @Given("a boarding reservation for listing exists with {int} nights")
    public void aBoardingReservationForListingExists(int nights) {
        created = ApiSupport.uniqueReservationBody(nights);
        Response r = Harness.authed().contentType("application/json").body(created).post("/api/reservations");
        assertThat(r.statusCode()).as("reservation creation: " + r.asString()).isIn(200, 201);
    }

    @When("the boarding reservation with an unknown id is requested")
    public void theBoardingReservationWithAnUnknownIdIsRequested() {
        response = Harness.authed().get("/api/reservations/2147483000");
    }

    @When("boarding reservations are listed")
    public void boardingReservationsAreListed() {
        response = Harness.authed().get("/api/reservations");
    }

    @When("boarding reservations are listed with query parameter {string} set to {string}")
    public void boardingReservationsAreListedWithQueryParameter(String name, String value) {
        response = Harness.authed().queryParam(name, value).get("/api/reservations");
    }

    @Then("the boarding reservation query responds with status {int}")
    public void theBoardingReservationQueryRespondsWithStatus(int status) {
        assertThat(response.statusCode()).as("response: " + response.asString()).isEqualTo(status);
    }

    @Then("the boarding reservation list contains the created pet name")
    public void theBoardingReservationListContainsTheCreatedPetName() {
        assertThat(response.asString()).contains(String.valueOf(created.get("petName")));
    }
}
