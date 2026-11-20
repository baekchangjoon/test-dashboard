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

public class ReservationValidationSteps {

    private Response lastResponse;
    private String reservationId;
    private Map<String, Object> existingBody;

    @When("the client submits an invalid boarding reservation of kind {word}")
    public void submitInvalid(String kind) {
        if ("empty-body".equals(kind)) {
            lastResponse = Harness.authed().contentType("application/json").body("{}").post("/api/reservations");
            return;
        }
        Map<String, Object> body = ApiSupport.randomReservationBody(2);
        if ("blank-pet-name".equals(kind)) {
            body.put("petName", "");
        } else if ("zero-nights".equals(kind)) {
            body.put("nights", 0);
        } else {
            throw new IllegalArgumentException("Unknown invalid kind: " + kind);
        }
        lastResponse = Harness.authed().contentType("application/json").body(body).post("/api/reservations");
    }

    @Given("a boarding reservation exists for a random room and check-in date")
    public void existingReservation() {
        existingBody = ApiSupport.randomReservationBody(2);
        Response response = Harness.authed().contentType("application/json").body(existingBody).post("/api/reservations");
        assertThat(response.statusCode()).as("create status, body: %s", response.asString()).isBetween(200, 299);
        reservationId = ApiSupport.extractId(response);
        assertThat(reservationId).isNotBlank();
    }

    @When("another boarding reservation is submitted for the same room and check-in date")
    public void duplicateBooking() {
        String s = ApiSupport.suffix();
        Map<String, Object> body = new HashMap<>(existingBody);
        body.put("petName", "Other" + s);
        body.put("ownerEmail", "other" + s + "@example.com");
        lastResponse = Harness.authed().contentType("application/json").body(body).post("/api/reservations");
    }

    @When("the existing boarding reservation is updated with zero nights")
    public void updateZeroNights() {
        Map<String, Object> body = new HashMap<>(existingBody);
        body.put("nights", 0);
        lastResponse = Harness.authed().contentType("application/json").body(body).put("/api/reservations/" + reservationId);
    }

    @Then("the boarding reservation is rejected with status {int}")
    public void rejectedWith(int status) {
        assertThat(lastResponse.statusCode()).as("body: %s", lastResponse.asString()).isEqualTo(status);
    }
}
