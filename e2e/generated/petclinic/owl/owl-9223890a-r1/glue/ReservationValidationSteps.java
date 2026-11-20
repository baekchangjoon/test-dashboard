package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.LinkedHashMap;
import java.util.Map;
import td.harness.Harness;

public class ReservationValidationSteps {

    private Response response;
    private Map<String, Object> firstBody;
    private String firstId;
    private Map<String, Object> secondBody;
    private String secondId;

    private Response post(Object body) {
        return Harness.authed().contentType("application/json").body(body).post("/api/reservations");
    }

    private Response put(String id, Map<String, Object> body) {
        return Harness.authed().contentType("application/json").body(body).put("/api/reservations/" + id);
    }

    private Map<String, Object> copyForNewPet(Map<String, Object> source) {
        Map<String, Object> body = new LinkedHashMap<>(source);
        String petName = ApiSupport.uniqueName("Pet");
        body.put("petName", petName);
        body.put("ownerEmail", petName.toLowerCase() + "@example.com");
        return body;
    }

    @When("the validation client submits an invalid reservation of kind {string}")
    public void submitsInvalidReservation(String kind) {
        Map<String, Object> body = ApiSupport.randomReservation(2);
        switch (kind) {
            case "empty-body":
                response = post("{}");
                return;
            case "blank-pet-name":
                body.put("petName", "   ");
                break;
            case "zero-nights":
                body.put("nights", 0);
                break;
            case "negative-nights":
                body.put("nights", -3);
                break;
            case "zero-animals":
                body.put("animalCount", 0);
                break;
            default:
                throw new IllegalArgumentException("Unknown invalid reservation kind: " + kind);
        }
        response = post(body);
    }

    @Given("the validation client has booked a room on a future date")
    public void hasBookedARoom() {
        firstBody = ApiSupport.randomReservation(2);
        Response created = post(firstBody);
        assertThat(created.statusCode()).as("booking status, body: %s", ApiSupport.text(created)).isIn(200, 201);
        firstId = ApiSupport.extractId(created);
        assertThat(firstId).as("id of the first reservation").isNotBlank();
    }

    @Given("the validation client has booked the same room {int} days later")
    public void hasBookedSameRoomLater(int days) {
        secondBody = copyForNewPet(firstBody);
        secondBody.put("checkInDate", ApiSupport.plusDays(String.valueOf(firstBody.get("checkInDate")), days));
        Response created = post(secondBody);
        assertThat(created.statusCode()).as("booking status, body: %s", ApiSupport.text(created)).isIn(200, 201);
        secondId = ApiSupport.extractId(created);
        assertThat(secondId).as("id of the second reservation").isNotBlank();
    }

    @When("the validation client books the same room on the same date for another pet")
    public void booksSameRoomSameDate() {
        response = post(copyForNewPet(firstBody));
    }

    @When("the validation client updates that reservation to {int} nights")
    public void updatesToNights(int nights) {
        Map<String, Object> body = new LinkedHashMap<>(firstBody);
        body.put("nights", nights);
        response = put(firstId, body);
    }

    @When("the validation client moves the later reservation onto the first check-in date")
    public void movesLaterReservation() {
        Map<String, Object> body = new LinkedHashMap<>(secondBody);
        body.put("checkInDate", firstBody.get("checkInDate"));
        response = put(secondId, body);
    }

    @Then("the validation response status is {int}")
    public void validationStatusIs(int status) {
        assertThat(response.statusCode()).as("body: %s", ApiSupport.text(response)).isEqualTo(status);
    }
}
