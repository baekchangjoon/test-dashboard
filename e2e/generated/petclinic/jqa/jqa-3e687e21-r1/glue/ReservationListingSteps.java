package glue;

import glue.support.ApiData;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.Map;
import td.harness.Harness;

import static org.assertj.core.api.Assertions.assertThat;

public class ReservationListingSteps {

    private Response response;
    private String petName;

    @Given("a boarding reservation for listing has been created")
    public void createForListing() {
        Map<String, Object> body = ApiData.reservationBody();
        petName = String.valueOf(body.get("petName"));
        Response r = Harness.authed().contentType("application/json").body(body).post("/api/reservations");
        assertThat(r.statusCode()).isIn(200, 201);
    }

    @When("the client lists boarding reservations")
    public void listReservations() {
        response = Harness.authed().get("/api/reservations");
    }

    @When("the client lists boarding reservations filtered by {string} equal to {string}")
    public void listFiltered(String param, String value) {
        response = Harness.authed().queryParam(param, value).get("/api/reservations");
    }

    @Then("the reservation listing responds with status {int}")
    public void listingStatus(int code) {
        assertThat(response.statusCode()).isEqualTo(code);
    }

    @Then("the listing includes the created reservation pet name")
    public void listingContainsPet() {
        assertThat(response.asString()).contains(petName);
    }
}
