package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.HashMap;
import java.util.Map;
import td.harness.Harness;

public class ReservationLifecycleSteps {

    private Response lastResponse;
    private String reservationId;
    private String expectedPetName;
    private Map<String, Object> reservationBody;

    @Given("a new boarding reservation has been created for the lifecycle test")
    public void createReservation() {
        reservationBody = ApiSupport.randomReservationBody(2);
        expectedPetName = String.valueOf(reservationBody.get("petName"));
        Response response = Harness.authed().contentType("application/json").body(reservationBody).post("/api/reservations");
        assertThat(response.statusCode()).as("create status, body: %s", response.asString()).isBetween(200, 299);
        reservationId = ApiSupport.extractId(response);
        assertThat(reservationId).as("created reservation id").isNotBlank();
    }

    @When("the client books a lifecycle reservation with promo code {word}")
    public void bookWithPromo(String promoCode) {
        reservationBody = ApiSupport.randomReservationBody(2);
        reservationBody.put("promoCode", promoCode);
        lastResponse = Harness.authed().contentType("application/json").body(reservationBody).post("/api/reservations");
    }

    @Then("the lifecycle booking is accepted with an id")
    public void bookingAccepted() {
        assertThat(lastResponse.statusCode()).as("body: %s", lastResponse.asString()).isBetween(200, 299);
        assertThat(ApiSupport.extractId(lastResponse)).isNotBlank();
    }

    @When("the client fetches the lifecycle reservation by its id")
    public void fetchReservation() {
        lastResponse = Harness.authed().get("/api/reservations/" + reservationId);
    }

    @When("the client renames the pet on the lifecycle reservation")
    public void renamePet() {
        Map<String, Object> updated = new HashMap<>(reservationBody);
        expectedPetName = "Renamed" + ApiSupport.suffix();
        updated.put("petName", expectedPetName);
        lastResponse = Harness.authed().contentType("application/json").body(updated).put("/api/reservations/" + reservationId);
    }

    @When("the client deletes the lifecycle reservation")
    public void deleteReservation() {
        lastResponse = Harness.authed().delete("/api/reservations/" + reservationId);
    }

    @When("the client fetches a lifecycle reservation with an unknown id")
    public void fetchUnknown() {
        lastResponse = Harness.authed().get("/api/reservations/" + ApiSupport.UNKNOWN_ID);
    }

    @When("the client updates a lifecycle reservation with an unknown id")
    public void updateUnknown() {
        Map<String, Object> body = ApiSupport.randomReservationBody(2);
        lastResponse = Harness.authed().contentType("application/json").body(body).put("/api/reservations/" + ApiSupport.UNKNOWN_ID);
    }

    @When("the client deletes a lifecycle reservation with an unknown id")
    public void deleteUnknown() {
        lastResponse = Harness.authed().delete("/api/reservations/" + ApiSupport.UNKNOWN_ID);
    }

    @Then("the lifecycle reservation response has status {int}")
    public void hasStatus(int status) {
        assertThat(lastResponse.statusCode()).as("body: %s", lastResponse.asString()).isEqualTo(status);
    }

    @Then("the lifecycle reservation response is successful")
    public void isSuccessful() {
        assertThat(lastResponse.statusCode()).as("body: %s", lastResponse.asString()).isBetween(200, 299);
    }

    @Then("the lifecycle reservation response is a client error")
    public void isClientError() {
        assertThat(lastResponse.statusCode()).as("body: %s", lastResponse.asString()).isBetween(400, 499);
    }

    @Then("the fetched lifecycle reservation shows the expected pet name")
    public void showsPetName() {
        assertThat(lastResponse.jsonPath().getString("petName")).isEqualTo(expectedPetName);
    }
}
