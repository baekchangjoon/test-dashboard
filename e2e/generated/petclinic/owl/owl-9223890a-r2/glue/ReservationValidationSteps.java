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

    private Map<String, Object> body;
    private String reservationId;
    private Response response;

    @When("a reservation is submitted with the invalid variation {string}")
    public void submitInvalid(String variation) {
        if ("empty body".equals(variation)) {
            response = Harness.authed().contentType("application/json").body("{}").post("/api/reservations");
            return;
        }
        Map<String, Object> payload = ApiSupport.reservationBody(3);
        switch (variation) {
            case "zero nights" -> payload.put("nights", 0);
            case "negative nights" -> payload.put("nights", -1);
            case "blank pet name" -> payload.put("petName", "");
            default -> throw new IllegalArgumentException("Unknown variation: " + variation);
        }
        response = ApiSupport.postJson("/api/reservations", payload);
    }

    @Then("the reservation validation response status is {int}")
    public void statusIs(int expected) {
        assertThat(response.statusCode()).as(response.asString()).isEqualTo(expected);
    }

    @Given("a reservation has been booked for the conflict test")
    public void bookReservation() {
        body = ApiSupport.reservationBody(3);
        Response created = ApiSupport.postJson("/api/reservations", body);
        assertThat(created.statusCode()).as("create response: %s", created.asString()).isIn(200, 201);
        reservationId = ApiSupport.extractId(created);
        assertThat(reservationId).isNotBlank();
    }

    @When("the identical reservation is booked again")
    public void bookAgain() {
        response = ApiSupport.postJson("/api/reservations", new HashMap<>(body));
    }

    @When("the booked reservation is updated to {int} nights in the validation test")
    public void updateNights(int nights) {
        Map<String, Object> update = new HashMap<>(body);
        update.put("nights", nights);
        response = ApiSupport.putJson("/api/reservations/" + reservationId, update);
    }
}
