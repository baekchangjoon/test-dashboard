package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiData;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.HashMap;
import java.util.Map;
import td.harness.Harness;

public class ReservationLifecycleSteps {

    private Map<String, Object> payload;
    private Response response;
    private Integer reservationId;

    @Given("a unique boarding reservation payload is prepared")
    public void aUniqueBoardingReservationPayloadIsPrepared() {
        payload = ApiData.reservationPayload();
    }

    @Given("a unique boarding reservation payload is prepared with promo code {string}")
    public void aUniquePayloadWithPromoCode(String promoCode) {
        payload = ApiData.reservationPayload();
        payload.put("promoCode", promoCode);
    }

    @When("the boarding reservation is submitted")
    public void theBoardingReservationIsSubmitted() {
        response = ApiData.postReservation(payload);
        reservationId = ApiData.extractId(response);
    }

    @Given("a boarding reservation has been created")
    public void aBoardingReservationHasBeenCreated() {
        aUniqueBoardingReservationPayloadIsPrepared();
        theBoardingReservationIsSubmitted();
        assertThat(response.statusCode()).as(ApiData.describe(response)).isBetween(200, 299);
        assertThat(reservationId).as("id of the created reservation").isNotNull();
    }

    @When("the created boarding reservation is fetched by id")
    public void theCreatedReservationIsFetched() {
        response = Harness.authed().get("/api/reservations/" + reservationId);
    }

    @When("the boarding reservation is updated to {int} nights")
    public void theReservationIsUpdatedToNights(int nights) {
        Map<String, Object> update = new HashMap<>(payload);
        update.put("nights", nights);
        response = Harness.authed().contentType("application/json").body(update)
                .put("/api/reservations/" + reservationId);
    }

    @When("the created boarding reservation is deleted")
    public void theCreatedReservationIsDeleted() {
        response = Harness.authed().delete("/api/reservations/" + reservationId);
    }

    @When("a boarding reservation with an unknown id is fetched")
    public void anUnknownReservationIsFetched() {
        response = Harness.authed().get("/api/reservations/" + ApiData.unknownId());
    }

    @When("a boarding reservation with an unknown id is deleted")
    public void anUnknownReservationIsDeleted() {
        response = Harness.authed().delete("/api/reservations/" + ApiData.unknownId());
    }

    @When("a boarding reservation with an unknown id is updated")
    public void anUnknownReservationIsUpdated() {
        response = Harness.authed().contentType("application/json").body(ApiData.reservationPayload())
                .put("/api/reservations/" + ApiData.unknownId());
    }

    @Then("the boarding reservation request succeeds")
    public void theRequestSucceeds() {
        assertThat(response.statusCode()).as(ApiData.describe(response)).isBetween(200, 299);
    }

    @Then("the boarding reservation response carries an identifier")
    public void theResponseCarriesAnIdentifier() {
        assertThat(reservationId).as(ApiData.describe(response)).isNotNull();
    }

    @Then("the fetched boarding reservation matches the submitted pet name and owner email")
    public void theFetchedReservationMatches() {
        assertThat(response.jsonPath().getString("petName")).isEqualTo(payload.get("petName"));
        assertThat(response.jsonPath().getString("ownerEmail")).isEqualTo(payload.get("ownerEmail"));
    }

    @Then("fetching the boarding reservation again shows {int} nights")
    public void fetchingAgainShowsNights(int nights) {
        Response fetched = Harness.authed().get("/api/reservations/" + reservationId);
        assertThat(fetched.statusCode()).as(ApiData.describe(fetched)).isBetween(200, 299);
        assertThat(fetched.jsonPath().getInt("nights")).isEqualTo(nights);
    }

    @Then("fetching the deleted boarding reservation returns status {int}")
    public void fetchingDeletedReturnsStatus(int status) {
        Response fetched = Harness.authed().get("/api/reservations/" + reservationId);
        assertThat(fetched.statusCode()).as(ApiData.describe(fetched)).isEqualTo(status);
    }

    @Then("the boarding reservation response status is {int}")
    public void theResponseStatusIs(int status) {
        assertThat(response.statusCode()).as(ApiData.describe(response)).isEqualTo(status);
    }

    @Then("the boarding reservation request is rejected with a client error")
    public void theRequestIsRejected() {
        assertThat(response.statusCode()).as(ApiData.describe(response)).isBetween(400, 499);
    }
}
