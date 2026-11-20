package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiData;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.HashMap;
import java.util.Map;
import td.harness.Harness;

public class ReservationLifecycleSteps {

    private Map<String, Object> body;
    private Response createResponse;
    private Response response;
    private Integer reservationId;

    @Given("a new boarding reservation for a unique pet staying {int} nights")
    public void aNewBoardingReservation(int nights) {
        body = ApiData.reservationBody(ApiData.uniqueName("Pet"), nights);
        createResponse = ApiData.createReservation(body);
        assertThat(createResponse.statusCode()).as(createResponse.asString()).isBetween(200, 299);
        reservationId = ApiData.extractId(createResponse);
        assertThat(reservationId).as("created reservation id").isNotNull();
    }

    @When("the client fetches that boarding reservation by its id")
    public void fetchThatReservation() {
        response = Harness.authed().get("/api/reservations/" + reservationId);
    }

    @Then("the boarding reservation fetch returns status {int}")
    public void fetchReturnsStatus(int status) {
        assertThat(response.statusCode()).as(response.asString()).isEqualTo(status);
    }

    @Then("the fetched boarding reservation shows the pet name and owner email that were sent")
    public void fetchedShowsSentFields() {
        assertThat(response.jsonPath().getString("petName")).isEqualTo(body.get("petName"));
        assertThat(response.jsonPath().getString("ownerEmail")).isEqualTo(body.get("ownerEmail"));
    }

    @Then("the boarding reservation creation response contains an id")
    public void creationContainsId() {
        assertThat(reservationId).isNotNull();
        assertThat(reservationId.intValue()).isPositive();
    }

    @When("the client books a boarding reservation for a unique pet with promo code {string}")
    public void bookWithPromo(String promoCode) {
        body = ApiData.reservationBody(ApiData.uniqueName("Pet"), 3);
        body.put("promoCode", promoCode);
        createResponse = ApiData.createReservation(body);
    }

    @Then("the boarding reservation creation succeeds")
    public void creationSucceeds() {
        assertThat(createResponse.statusCode()).as(createResponse.asString()).isBetween(200, 299);
        assertThat(ApiData.extractId(createResponse)).isNotNull();
    }

    @When("the client updates that boarding reservation to {int} nights")
    public void updateNights(int nights) {
        Map<String, Object> update = new HashMap<>(body);
        update.put("nights", nights);
        response = Harness.authed().contentType("application/json").body(update)
                .put("/api/reservations/" + reservationId);
    }

    @Then("the boarding reservation update returns a success status")
    public void updateSucceeds() {
        assertThat(response.statusCode()).as(response.asString()).isBetween(200, 299);
    }

    @Then("reading that boarding reservation again shows {int} nights")
    public void readAgainShowsNights(int nights) {
        Response read = Harness.authed().get("/api/reservations/" + reservationId);
        assertThat(read.statusCode()).isEqualTo(200);
        assertThat(read.jsonPath().getInt("nights")).isEqualTo(nights);
    }

    @When("the client deletes that boarding reservation")
    public void deleteThatReservation() {
        response = Harness.authed().delete("/api/reservations/" + reservationId);
    }

    @Then("the boarding reservation deletion returns a success status")
    public void deletionSucceeds() {
        assertThat(response.statusCode()).as(response.asString()).isBetween(200, 299);
    }

    @Then("reading that boarding reservation again returns status {int}")
    public void readAgainReturnsStatus(int status) {
        Response read = Harness.authed().get("/api/reservations/" + reservationId);
        assertThat(read.statusCode()).isEqualTo(status);
    }
}
