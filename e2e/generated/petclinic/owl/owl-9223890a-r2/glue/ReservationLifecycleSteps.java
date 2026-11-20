package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.HashMap;
import java.util.Map;
import td.harness.Harness;

public class ReservationLifecycleSteps {

    private static final String UNKNOWN_ID = "987654321";

    private Map<String, Object> body;
    private String reservationId;
    private Response response;

    @Given("a new boarding reservation has been created for the lifecycle test")
    public void aNewReservationHasBeenCreated() {
        body = ApiSupport.reservationBody(3);
        Response created = ApiSupport.postJson("/api/reservations", body);
        assertThat(created.statusCode()).as("create response: %s", created.asString()).isIn(200, 201);
        reservationId = ApiSupport.extractId(created);
        assertThat(reservationId).as("id of the created reservation").isNotBlank();
    }

    @When("a boarding reservation is created for the lifecycle test with promo code {string}")
    public void createWithPromo(String promo) {
        body = ApiSupport.reservationBody(3);
        body.put("promoCode", promo);
        response = ApiSupport.postJson("/api/reservations", body);
    }

    @Then("the lifecycle reservation creation succeeds with an id")
    public void creationSucceeds() {
        assertThat(response.statusCode()).as(response.asString()).isIn(200, 201);
        assertThat(ApiSupport.extractId(response)).isNotBlank();
    }

    @When("the lifecycle reservation is fetched by its id")
    public void fetchById() {
        response = Harness.authed().get("/api/reservations/" + reservationId);
    }

    @Then("the lifecycle response status is {int}")
    public void statusIs(int expected) {
        assertThat(response.statusCode()).as(response.asString()).isEqualTo(expected);
    }

    @Then("the lifecycle response echoes the submitted reservation details")
    public void echoesDetails() {
        assertThat(response.jsonPath().getString("petName")).isEqualTo(body.get("petName"));
        assertThat(response.jsonPath().getString("ownerEmail")).isEqualTo(body.get("ownerEmail"));
        assertThat(response.jsonPath().getInt("roomNumber")).isEqualTo(body.get("roomNumber"));
        assertThat(response.jsonPath().getInt("nights")).isEqualTo(body.get("nights"));
    }

    @When("the lifecycle reservation is updated to {int} nights")
    public void updateNights(int nights) {
        Map<String, Object> update = new HashMap<>(body);
        update.put("nights", nights);
        response = ApiSupport.putJson("/api/reservations/" + reservationId, update);
    }

    @Then("the lifecycle request succeeds")
    public void requestSucceeds() {
        assertThat(response.statusCode()).as(response.asString()).isBetween(200, 299);
    }

    @Then("fetching the lifecycle reservation shows {int} nights")
    public void fetchShowsNights(int nights) {
        Response fetched = Harness.authed().get("/api/reservations/" + reservationId);
        assertThat(fetched.statusCode()).as(fetched.asString()).isEqualTo(200);
        assertThat(fetched.jsonPath().getInt("nights")).isEqualTo(nights);
    }

    @When("the lifecycle reservation is deleted")
    public void deleteReservation() {
        response = Harness.authed().delete("/api/reservations/" + reservationId);
    }

    @Then("fetching the deleted lifecycle reservation returns status {int}")
    public void fetchDeleted(int expected) {
        Response fetched = Harness.authed().get("/api/reservations/" + reservationId);
        assertThat(fetched.statusCode()).as(fetched.asString()).isEqualTo(expected);
    }

    @When("an unknown reservation id is fetched in the lifecycle test")
    public void fetchUnknown() {
        response = Harness.authed().get("/api/reservations/" + UNKNOWN_ID);
    }

    @When("an unknown reservation id is updated in the lifecycle test")
    public void updateUnknown() {
        response = ApiSupport.putJson("/api/reservations/" + UNKNOWN_ID, ApiSupport.reservationBody(3));
    }

    @When("an unknown reservation id is deleted in the lifecycle test")
    public void deleteUnknown() {
        response = Harness.authed().delete("/api/reservations/" + UNKNOWN_ID);
    }

    @Then("the lifecycle response is a client error")
    public void clientError() {
        assertThat(response.statusCode()).as(response.asString()).isBetween(400, 499);
    }
}
