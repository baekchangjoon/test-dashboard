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

public class ReservationLifecycleSteps {

    private Map<String, Object> submitted;
    private String reservationId;
    private Response response;

    @Given("a new boarding reservation has been created for the lifecycle test")
    public void aNewReservationHasBeenCreated() {
        submitted = ApiSupport.newReservationBody(2);
        Response created = Harness.authed().contentType("application/json").body(submitted).post("/api/reservations");
        assertThat(created.statusCode()).as("create reservation: %s", created.asString()).isBetween(200, 299);
        reservationId = ApiSupport.extractId(created);
        assertThat(reservationId).as("created reservation id").isNotBlank();
    }

    @When("the lifecycle reservation is fetched by its id")
    public void fetchById() {
        response = Harness.authed().get("/api/reservations/" + reservationId);
    }

    @Then("the lifecycle response status is {int}")
    public void responseStatusIs(int expected) {
        assertThat(response.statusCode()).as("response body: %s", response.asString()).isEqualTo(expected);
    }

    @Then("the fetched lifecycle reservation matches the submitted pet name and nights")
    public void fetchedReservationMatches() {
        assertThat(response.jsonPath().getString("petName")).isEqualTo(submitted.get("petName"));
        assertThat(ApiSupport.intField(response, "nights")).isEqualTo(submitted.get("nights"));
    }

    @When("a boarding reservation is created with promo code {string}")
    public void createWithPromoCode(String promoCode) {
        submitted = ApiSupport.newReservationBody(2);
        submitted.put("promoCode", promoCode);
        response = Harness.authed().contentType("application/json").body(submitted).post("/api/reservations");
    }

    @Then("the lifecycle reservation creation succeeds with an id")
    public void creationSucceedsWithId() {
        assertThat(response.statusCode()).as("response body: %s", response.asString()).isBetween(200, 299);
        assertThat(ApiSupport.extractId(response)).isNotBlank();
    }

    @When("the lifecycle reservation is updated to {int} nights")
    public void updateNights(int nights) {
        Map<String, Object> body = new HashMap<>(submitted);
        body.put("nights", nights);
        response = Harness.authed().contentType("application/json").body(body).put("/api/reservations/" + reservationId);
    }

    @Then("the lifecycle reservation update succeeds")
    public void updateSucceeds() {
        assertThat(response.statusCode()).as("response body: %s", response.asString()).isBetween(200, 299);
    }

    @Then("fetching the lifecycle reservation shows {int} nights")
    public void fetchShowsNights(int nights) {
        Response fetched = Harness.authed().get("/api/reservations/" + reservationId);
        assertThat(fetched.statusCode()).as("response body: %s", fetched.asString()).isEqualTo(200);
        assertThat(ApiSupport.intField(fetched, "nights")).isEqualTo(nights);
    }

    @When("the lifecycle reservation is deleted")
    public void deleteReservation() {
        response = Harness.authed().delete("/api/reservations/" + reservationId);
    }

    @Then("the lifecycle reservation deletion succeeds")
    public void deletionSucceeds() {
        assertThat(response.statusCode()).as("response body: %s", response.asString()).isBetween(200, 299);
    }

    @Then("fetching the lifecycle reservation returns status {int}")
    public void fetchReturnsStatus(int expected) {
        Response fetched = Harness.authed().get("/api/reservations/" + reservationId);
        assertThat(fetched.statusCode()).as("response body: %s", fetched.asString()).isEqualTo(expected);
    }

    @When("a lifecycle {string} request is sent for an unknown reservation id")
    public void requestForUnknownId(String method) {
        String path = "/api/reservations/" + ApiSupport.UNKNOWN_ID;
        switch (method) {
            case "GET":
                response = Harness.authed().get(path);
                break;
            case "PUT":
                response = Harness.authed().contentType("application/json").body(ApiSupport.newReservationBody(2)).put(path);
                break;
            case "DELETE":
                response = Harness.authed().delete(path);
                break;
            default:
                throw new IllegalArgumentException("Unsupported method: " + method);
        }
    }
}
