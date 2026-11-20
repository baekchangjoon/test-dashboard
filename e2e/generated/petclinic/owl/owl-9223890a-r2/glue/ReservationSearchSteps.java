package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.Map;
import td.harness.Harness;

public class ReservationSearchSteps {

    private Map<String, Object> body;
    private Response response;

    @Given("a reservation with {int} nights exists for the search test")
    public void reservationExists(int nights) {
        body = ApiSupport.reservationBody(nights);
        Response created = ApiSupport.postJson("/api/reservations", body);
        assertThat(created.statusCode()).as("create response: %s", created.asString()).isIn(200, 201);
    }

    @When("reservations are listed without filters")
    public void listWithoutFilters() {
        response = Harness.authed().get("/api/reservations");
    }

    @When("reservations are listed with query parameter {string} set to {string}")
    public void listWithFilter(String name, String value) {
        response = Harness.authed().queryParam(name, value).get("/api/reservations");
    }

    @Then("the search response status is {int}")
    public void statusIs(int expected) {
        assertThat(response.statusCode()).as(response.asString()).isEqualTo(expected);
    }

    @Then("the search results include the created pet name")
    public void resultsIncludePetName() {
        assertThat(response.asString()).contains((String) body.get("petName"));
    }
}
