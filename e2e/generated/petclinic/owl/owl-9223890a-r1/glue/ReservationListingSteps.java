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

    private Response response;
    private Response created;
    private String petName;

    @Given("the listing client has booked a reservation for {int} nights")
    public void hasBookedReservation(int nights) {
        Map<String, Object> body = ApiSupport.randomReservation(nights);
        petName = String.valueOf(body.get("petName"));
        created = Harness.authed().contentType("application/json").body(body).post("/api/reservations");
        assertThat(created.statusCode()).as("booking status, body: %s", ApiSupport.text(created)).isIn(200, 201);
    }

    @When("the listing client lists all reservations")
    public void listsAll() {
        response = Harness.authed().get("/api/reservations");
    }

    @When("the listing client lists reservations with query parameter {string} set to {string}")
    public void listsWithQuery(String name, String value) {
        response = Harness.authed().queryParam(name, value).get("/api/reservations");
    }

    @When("the listing client lists reservations filtered by the booked price tier")
    public void listsByBookedTier() {
        String tier = ApiSupport.fieldText(created, "priceTier");
        assertThat(tier).as("priceTier of the booked reservation, body: %s", ApiSupport.text(created)).isNotBlank();
        response = Harness.authed().queryParam("tier", tier).get("/api/reservations");
    }

    @Then("the listing response status is {int}")
    public void listingStatusIs(int status) {
        assertThat(response.statusCode()).as("body: %s", ApiSupport.text(response)).isEqualTo(status);
    }

    @Then("the listing response mentions the booked pet name")
    public void mentionsPetName() {
        assertThat(ApiSupport.text(response)).contains(petName);
    }
}
