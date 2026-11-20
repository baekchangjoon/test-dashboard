package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.Map;
import td.harness.Harness;

public class ReservationChangesSteps {

    private static final String UNKNOWN_ID = "2147483000";

    private Map<String, Object> body;
    private String id;
    private String newPetName;
    private Response response;

    private Response put(String reservationId, Map<String, Object> payload) {
        return Harness.authed().contentType("application/json").body(payload).put("/api/reservations/" + reservationId);
    }

    @Given("an existing boarding reservation to change")
    public void anExistingBoardingReservationToChange() {
        body = ApiSupport.uniqueReservationBody(1);
        Response r = Harness.authed().contentType("application/json").body(body).post("/api/reservations");
        assertThat(r.statusCode()).as("reservation creation: " + r.asString()).isIn(200, 201);
        id = ApiSupport.extractId(r);
        assertThat(id).as("created reservation id").isNotNull();
    }

    @When("the boarding reservation is updated with a new pet name")
    public void theBoardingReservationIsUpdatedWithANewPetName() {
        newPetName = ApiSupport.petName();
        Map<String, Object> payload = ApiSupport.copy(body);
        payload.put("petName", newPetName);
        response = put(id, payload);
    }

    @When("the boarding reservation is updated with {int} nights")
    public void theBoardingReservationIsUpdatedWithNights(int nights) {
        Map<String, Object> payload = ApiSupport.copy(body);
        payload.put("nights", nights);
        response = put(id, payload);
    }

    @When("an update is sent for an unknown boarding reservation id")
    public void anUpdateIsSentForAnUnknownBoardingReservationId() {
        response = put(UNKNOWN_ID, ApiSupport.uniqueReservationBody(1));
    }

    @When("the boarding reservation is deleted")
    public void theBoardingReservationIsDeleted() {
        response = Harness.authed().delete("/api/reservations/" + id);
    }

    @When("the boarding reservation is deleted again")
    public void theBoardingReservationIsDeletedAgain() {
        response = Harness.authed().delete("/api/reservations/" + id);
    }

    @When("a delete is sent for an unknown boarding reservation id")
    public void aDeleteIsSentForAnUnknownBoardingReservationId() {
        response = Harness.authed().delete("/api/reservations/" + UNKNOWN_ID);
    }

    @Then("the boarding reservation change succeeds")
    public void theBoardingReservationChangeSucceeds() {
        assertThat(response.statusCode()).as("response: " + response.asString()).isBetween(200, 299);
    }

    @Then("the boarding reservation change responds with status {int}")
    public void theBoardingReservationChangeRespondsWithStatus(int status) {
        assertThat(response.statusCode()).as("response: " + response.asString()).isEqualTo(status);
    }

    @Then("the boarding reservation now shows the new pet name")
    public void theBoardingReservationNowShowsTheNewPetName() {
        Response fetched = Harness.authed().get("/api/reservations/" + id);
        assertThat(fetched.statusCode()).isEqualTo(200);
        assertThat(fetched.jsonPath().getString("petName")).isEqualTo(newPetName);
    }

    @Then("the repeated boarding reservation deletion is rejected")
    public void theRepeatedBoardingReservationDeletionIsRejected() {
        assertThat(response.statusCode()).as("response: " + response.asString()).isIn(404, 409);
    }
}
