package glue;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

public class ReservationValidationSteps {

    private Map<String, Object> prepared;
    private Map<String, Object> firstBody;
    private String firstId;
    private Map<String, Object> secondBody;
    private String secondId;
    private Response response;

    @When("the validation client submits an empty reservation request")
    public void submitEmpty() {
        response = Harness.authed().contentType("application/json").body("{}").post("/api/reservations");
    }

    @Given("a valid reservation request prepared for the validation check")
    public void prepareValid() {
        prepared = ApiSupport.uniqueReservationBody(2);
    }

    @Given("the prepared validation request has {string} set to {string}")
    public void setField(String field, String value) {
        if (field.equals("nights") || field.equals("animalCount") || field.equals("roomNumber")) {
            prepared.put(field, Integer.parseInt(value));
        } else {
            prepared.put(field, value);
        }
    }

    @When("the validation client submits the prepared reservation request")
    public void submitPrepared() {
        response = Harness.authed().contentType("application/json").body(prepared).post("/api/reservations");
    }

    @Given("an existing reservation created for the conflict check")
    public void createFirst() {
        firstBody = ApiSupport.uniqueReservationBody(2);
        Response created = ApiSupport.createReservation(firstBody);
        assertThat(created.statusCode()).as("create status, body: %s", created.asString()).isBetween(200, 299);
        firstId = ApiSupport.extractId(created);
        assertThat(firstId).as("first reservation id").isNotBlank();
    }

    @Given("a second reservation in a different slot created for the conflict check")
    public void createSecond() {
        secondBody = ApiSupport.uniqueReservationBody(2);
        int firstRoom = ((Integer) firstBody.get("roomNumber")) % 20 + 1;
        secondBody.put("roomNumber", firstRoom);
        Response created = ApiSupport.createReservation(secondBody);
        assertThat(created.statusCode()).as("create status, body: %s", created.asString()).isBetween(200, 299);
        secondId = ApiSupport.extractId(created);
        assertThat(secondId).as("second reservation id").isNotBlank();
    }

    @When("the validation client submits another reservation for the same room and check-in date")
    public void submitDuplicate() {
        Map<String, Object> duplicate = ApiSupport.uniqueReservationBody(2);
        duplicate.put("roomNumber", firstBody.get("roomNumber"));
        duplicate.put("checkInDate", firstBody.get("checkInDate"));
        response = Harness.authed().contentType("application/json").body(duplicate).post("/api/reservations");
    }

    @When("the validation client moves the second reservation onto the room and date of the first")
    public void moveSecondOntoFirst() {
        Map<String, Object> update = new HashMap<>(secondBody);
        update.put("roomNumber", firstBody.get("roomNumber"));
        update.put("checkInDate", firstBody.get("checkInDate"));
        response = Harness.authed().contentType("application/json").body(update)
                .put("/api/reservations/" + secondId);
    }

    @When("the validation client updates the existing reservation with {int} nights")
    public void updateNights(int nights) {
        Map<String, Object> update = new HashMap<>(firstBody);
        update.put("nights", nights);
        response = Harness.authed().contentType("application/json").body(update)
                .put("/api/reservations/" + firstId);
    }

    @Then("the validation response status is {int}")
    public void statusIs(int expected) {
        assertThat(response.statusCode()).as("status, body: %s", response.asString()).isEqualTo(expected);
    }
}
