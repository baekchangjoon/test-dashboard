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

    private String petName;
    private Response response;

    @Given("a reservation created for the listing check with {int} nights")
    public void createForListing(int nights) {
        Map<String, Object> body = ApiSupport.uniqueReservationBody(nights);
        petName = (String) body.get("petName");
        Response created = ApiSupport.createReservation(body);
        assertThat(created.statusCode()).as("create status, body: %s", created.asString()).isBetween(200, 299);
    }

    @When("the listing client requests the reservation list")
    public void requestList() {
        response = Harness.authed().get("/api/reservations");
    }

    @When("the listing client requests reservations with minNights {int}")
    public void requestMinNights(int minNights) {
        response = Harness.authed().queryParam("minNights", minNights).get("/api/reservations");
    }

    @When("the listing client requests only recent reservations")
    public void requestRecent() {
        response = Harness.authed().queryParam("recentOnly", true).get("/api/reservations");
    }

    @When("the listing client requests reservations with tier {string}")
    public void requestTier(String tier) {
        response = Harness.authed().queryParam("tier", tier).get("/api/reservations");
    }

    @Then("the listing response status is {int}")
    public void statusIs(int expected) {
        assertThat(response.statusCode()).as("status, body: %s", response.asString()).isEqualTo(expected);
    }

    @Then("the listing response body is not empty")
    public void bodyNotEmpty() {
        assertThat(response.asString()).isNotBlank();
    }

    @Then("the listing response mentions the created pet name")
    public void mentionsPetName() {
        assertThat(response.asString()).contains(petName);
    }
}
