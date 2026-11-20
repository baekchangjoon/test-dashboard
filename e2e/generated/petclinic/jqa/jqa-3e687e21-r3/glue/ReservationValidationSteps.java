package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiData;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.Map;
import td.harness.Harness;

public class ReservationValidationSteps {

    private static final int UNKNOWN_ID = 987654321;

    private Map<String, Object> existing;
    private Response response;

    @When("the client submits an empty JSON object as a boarding reservation")
    public void submitEmptyObject() {
        response = Harness.authed().contentType("application/json").body("{}").post("/api/reservations");
    }

    @When("the client submits a boarding reservation without any request body")
    public void submitWithoutBody() {
        response = Harness.authed().contentType("application/json").post("/api/reservations");
    }

    @When("the client submits a boarding reservation for a unique pet with {int} nights")
    public void submitWithNights(int nights) {
        response = ApiData.postReservation(ApiData.reservationBody(ApiData.uniqueName("Pet"), nights));
    }

    @When("the client submits a boarding reservation with a blank pet name")
    public void submitBlankPetName() {
        Map<String, Object> body = ApiData.reservationBody(ApiData.uniqueName("Pet"), 2);
        body.put("petName", "");
        response = ApiData.postReservation(body);
    }

    @Given("an existing boarding reservation for a unique pet in the validation suite")
    public void existingReservation() {
        existing = ApiData.reservationBody(ApiData.uniqueName("Pet"), 2);
        Response created = ApiData.createReservation(existing);
        assertThat(created.statusCode()).as(created.asString()).isBetween(200, 299);
    }

    @When("the client books the same room on the same check-in date for another pet")
    public void bookSameRoomSameDate() {
        Map<String, Object> body = ApiData.reservationBody(ApiData.uniqueName("Pet"), 2);
        body.put("roomNumber", existing.get("roomNumber"));
        body.put("checkInDate", existing.get("checkInDate"));
        response = ApiData.postReservation(body);
    }

    @When("the client fetches a boarding reservation with an id that does not exist")
    public void fetchUnknown() {
        response = Harness.authed().get("/api/reservations/" + UNKNOWN_ID);
    }

    @When("the client updates a boarding reservation with an id that does not exist")
    public void updateUnknown() {
        Map<String, Object> body = ApiData.reservationBody(ApiData.uniqueName("Pet"), 2);
        response = Harness.authed().contentType("application/json").body(body)
                .put("/api/reservations/" + UNKNOWN_ID);
    }

    @When("the client deletes a boarding reservation with an id that does not exist")
    public void deleteUnknown() {
        response = Harness.authed().delete("/api/reservations/" + UNKNOWN_ID);
    }

    @Then("the boarding reservation request is rejected with status {int}")
    public void rejectedWithStatus(int status) {
        assertThat(response.statusCode()).as(response.asString()).isEqualTo(status);
    }
}
