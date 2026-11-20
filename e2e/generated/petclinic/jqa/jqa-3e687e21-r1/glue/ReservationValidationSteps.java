package glue;

import glue.support.ApiData;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.HashMap;
import java.util.Map;
import td.harness.Harness;

import static org.assertj.core.api.Assertions.assertThat;

public class ReservationValidationSteps {

    private Response response;
    private Map<String, Object> existing;
    private String existingId;

    @When("the client submits a boarding reservation without a request body")
    public void submitWithoutBody() {
        response = Harness.authed().contentType("application/json").post("/api/reservations");
    }

    @When("the client submits an empty boarding reservation object")
    public void submitEmptyObject() {
        response = Harness.authed().contentType("application/json").body("{}").post("/api/reservations");
    }

    @When("the client submits a boarding reservation where {string} is set to {string}")
    public void submitWithField(String field, String value) {
        Map<String, Object> body = ApiData.reservationBody();
        Object v = value;
        if (field.equals("nights") || field.equals("animalCount") || field.equals("roomNumber")) {
            v = Integer.parseInt(value);
        }
        body.put(field, v);
        response = Harness.authed().contentType("application/json").body(body).post("/api/reservations");
    }

    @Then("the reservation validation responds with status {int}")
    public void validationStatus(int code) {
        assertThat(response.statusCode()).isEqualTo(code);
    }

    @Given("a boarding reservation already occupies a room on a check-in date")
    public void existingReservation() {
        existing = ApiData.reservationBody();
        Response r = Harness.authed().contentType("application/json").body(existing).post("/api/reservations");
        assertThat(r.statusCode()).isIn(200, 201);
        existingId = ApiData.extractId(r);
        assertThat(existingId).isNotBlank();
    }

    @When("the client books the same room for the same check-in date")
    public void bookSameRoom() {
        Map<String, Object> body = ApiData.reservationBody();
        body.put("roomNumber", existing.get("roomNumber"));
        body.put("checkInDate", existing.get("checkInDate"));
        body.put("nights", existing.get("nights"));
        response = Harness.authed().contentType("application/json").body(body).post("/api/reservations");
    }

    @When("the client updates that occupied reservation setting nights to {int}")
    public void updateNights(int nights) {
        Map<String, Object> body = new HashMap<>(existing);
        body.put("nights", nights);
        response = Harness.authed().contentType("application/json").body(body).put("/api/reservations/" + existingId);
    }
}
