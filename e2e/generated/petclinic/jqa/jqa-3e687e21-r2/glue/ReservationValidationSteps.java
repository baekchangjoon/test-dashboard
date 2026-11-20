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

    private Map<String, Object> payload;
    private Response response;

    @When("an empty boarding reservation body is submitted")
    public void anEmptyBodyIsSubmitted() {
        response = Harness.authed().contentType("application/json").body("{}").post("/api/reservations");
    }

    @Given("a valid reservation validation payload")
    public void aValidPayload() {
        payload = ApiData.reservationPayload();
    }

    @Given("the reservation validation payload has no {string}")
    public void thePayloadHasNo(String field) {
        payload.remove(field);
    }

    @Given("the reservation validation payload sets {string} to {int}")
    public void thePayloadSets(String field, int value) {
        payload.put(field, value);
    }

    @When("the reservation validation payload is submitted")
    public void thePayloadIsSubmitted() {
        response = ApiData.postReservation(payload);
    }

    @Then("the reservation validation response status is {int}")
    public void theResponseStatusIs(int status) {
        assertThat(response.statusCode()).as(ApiData.describe(response)).isEqualTo(status);
    }
}
