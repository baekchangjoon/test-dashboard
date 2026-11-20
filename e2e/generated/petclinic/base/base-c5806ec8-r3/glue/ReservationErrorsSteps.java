package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.Map;
import td.harness.Harness;

public class ReservationErrorsSteps {

    private Map<String, Object> body;
    private String id;
    private Response response;

    @When("a boarding reservation is submitted with an empty body")
    public void aBoardingReservationIsSubmittedWithAnEmptyBody() {
        response = Harness.authed().contentType("application/json").body("{}").post("/api/reservations");
    }

    @When("a boarding reservation is submitted with {string} set to {int}")
    public void aBoardingReservationIsSubmittedWithFieldSetTo(String field, int value) {
        body = ApiSupport.newReservationBody();
        body.put(field, value);
        response = ApiSupport.postReservation(body);
    }

    @Given("a boarding reservation request body has been accepted once")
    public void aBoardingReservationRequestBodyHasBeenAcceptedOnce() {
        body = ApiSupport.newReservationBody();
        Response r = ApiSupport.createReservation(body);
        assertThat(r.statusCode()).as("first create: %s", r.asString()).isIn(200, 201);
    }

    @When("the identical boarding reservation request is submitted again")
    public void theIdenticalBoardingReservationRequestIsSubmittedAgain() {
        response = ApiSupport.postReservation(body);
    }

    @When("an unknown boarding reservation id is fetched")
    public void anUnknownBoardingReservationIdIsFetched() {
        response = Harness.authed().get("/api/reservations/" + ApiSupport.UNKNOWN_ID);
    }

    @When("an unknown boarding reservation id is updated")
    public void anUnknownBoardingReservationIdIsUpdated() {
        response = Harness.authed().contentType("application/json")
                .body(ApiSupport.toJson(ApiSupport.newReservationBody()))
                .put("/api/reservations/" + ApiSupport.UNKNOWN_ID);
    }

    @When("an unknown boarding reservation id is deleted")
    public void anUnknownBoardingReservationIdIsDeleted() {
        response = Harness.authed().delete("/api/reservations/" + ApiSupport.UNKNOWN_ID);
    }

    @Given("an existing boarding reservation for error checks")
    public void anExistingBoardingReservationForErrorChecks() {
        body = ApiSupport.newReservationBody();
        Response r = ApiSupport.createReservation(body);
        assertThat(r.statusCode()).as("create: %s", r.asString()).isIn(200, 201);
        id = ApiSupport.extractId(r);
        assertThat(id).isNotBlank();
    }

    @When("that boarding reservation is deleted twice")
    public void thatBoardingReservationIsDeletedTwice() {
        Response first = Harness.authed().delete("/api/reservations/" + id);
        assertThat(first.statusCode()).as("first delete: %s", first.asString()).isBetween(200, 299);
        response = Harness.authed().delete("/api/reservations/" + id);
    }

    @Then("the reservation error response has status {int}")
    public void theReservationErrorResponseHasStatus(int status) {
        assertThat(response.statusCode()).as("response: %s", response.asString()).isEqualTo(status);
    }

    @Then("the reservation error response is a client error")
    public void theReservationErrorResponseIsAClientError() {
        assertThat(response.statusCode()).as("response: %s", response.asString()).isBetween(400, 499);
    }
}
