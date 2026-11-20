package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiData;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.List;
import java.util.Map;
import td.harness.Harness;

public class ReservationListingSteps {

    private Response response;
    private Integer createdId;

    @Given("a boarding reservation for listing with {int} nights exists")
    public void aReservationWithNightsExists(int nights) {
        Map<String, Object> payload = ApiData.reservationPayload();
        payload.put("nights", nights);
        Response created = ApiData.postReservation(payload);
        assertThat(created.statusCode()).as(ApiData.describe(created)).isBetween(200, 299);
        createdId = ApiData.extractId(created);
        assertThat(createdId).as("id of the created reservation").isNotNull();
    }

    @When("boarding reservations are listed without filters")
    public void listedWithoutFilters() {
        response = Harness.authed().get("/api/reservations");
    }

    @When("boarding reservations are listed with query parameter {string} set to {string}")
    public void listedWithQueryParameter(String name, String value) {
        response = Harness.authed().queryParam(name, value).get("/api/reservations");
    }

    @Then("the reservation listing succeeds")
    public void theListingSucceeds() {
        assertThat(response.statusCode()).as(ApiData.describe(response)).isBetween(200, 299);
    }

    @Then("the reservation listing body is a JSON array")
    public void theListingIsAnArray() {
        List<Object> items = response.jsonPath().getList("$");
        assertThat(items).isNotNull();
    }

    @Then("every listed reservation has at least {int} nights")
    public void everyListedReservationHasAtLeast(int minNights) {
        List<Object> nights = response.jsonPath().getList("nights");
        assertThat(nights).isNotNull();
        for (Object n : nights) {
            if (n instanceof Number) {
                assertThat(((Number) n).intValue()).isGreaterThanOrEqualTo(minNights);
            }
        }
    }

    @Then("the listed reservations include the one just created")
    public void theListingIncludesCreated() {
        List<Object> ids = response.jsonPath().getList("id");
        assertThat(ApiData.listContainsId(ids, createdId)).as("listing contains id " + createdId).isTrue();
    }

    @Then("the reservation listing is rejected with a client error")
    public void theListingIsRejected() {
        assertThat(response.statusCode()).as(ApiData.describe(response)).isBetween(400, 499);
    }
}
