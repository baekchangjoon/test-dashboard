package glue;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

public class ReservationSearchSteps {

    private Map<String, Object> submitted;
    private Response response;

    @Given("a reservation has been created for the search test")
    public void reservationCreated() {
        submitted = ApiSupport.newReservationBody(2);
        Response created = Harness.authed().contentType("application/json").body(submitted).post("/api/reservations");
        assertThat(created.statusCode()).as("create reservation: %s", created.asString()).isBetween(200, 299);
    }

    @When("all reservations are listed")
    public void listAll() {
        response = Harness.authed().get("/api/reservations");
    }

    @When("reservations are listed with query {string}")
    public void listWithQuery(String query) {
        response = Harness.authed().get("/api/reservations?" + query);
    }

    @Then("the reservation search response status is {int}")
    public void searchStatusIs(int expected) {
        assertThat(response.statusCode()).as("response body: %s", response.asString()).isEqualTo(expected);
    }

    @Then("the reservation list contains the reservation created for the search test")
    public void listContainsCreated() {
        assertThat(response.asString()).contains(String.valueOf(submitted.get("petName")));
    }
}
