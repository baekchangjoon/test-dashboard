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

    private Map<String, Object> body;
    private String reservationId;
    private Response response;
    private String updatedPetName;

    @Given("a new boarding reservation has been created for the lifecycle check")
    public void createReservation() {
        body = ApiSupport.uniqueReservationBody(2);
        createAndRemember();
    }

    @Given("a new boarding reservation with promo code {string} has been created for the lifecycle check")
    public void createReservationWithPromo(String promo) {
        body = ApiSupport.uniqueReservationBody(2);
        body.put("promoCode", promo);
        createAndRemember();
    }

    private void createAndRemember() {
        Response created = ApiSupport.createReservation(body);
        assertThat(created.statusCode()).as("create status, body: %s", created.asString()).isBetween(200, 299);
        reservationId = ApiSupport.extractId(created);
        assertThat(reservationId).as("created reservation id").isNotBlank();
    }

    @When("the lifecycle client fetches the created reservation")
    public void fetchCreated() {
        response = Harness.authed().get("/api/reservations/" + reservationId);
    }

    @When("the lifecycle client updates the reservation with a new pet name and {int} nights")
    public void updateReservation(int nights) {
        Map<String, Object> update = new HashMap<>(body);
        updatedPetName = "Upd" + ApiSupport.suffix();
        update.put("petName", updatedPetName);
        update.put("nights", nights);
        response = Harness.authed().contentType("application/json").body(update)
                .put("/api/reservations/" + reservationId);
    }

    @When("the lifecycle client deletes the created reservation")
    public void deleteCreated() {
        response = Harness.authed().delete("/api/reservations/" + reservationId);
    }

    @When("the lifecycle client fetches a reservation id that was never created")
    public void fetchUnknown() {
        response = Harness.authed().get("/api/reservations/" + ApiSupport.unknownId());
    }

    @When("the lifecycle client updates a reservation id that was never created")
    public void updateUnknown() {
        Map<String, Object> update = ApiSupport.uniqueReservationBody(2);
        response = Harness.authed().contentType("application/json").body(update)
                .put("/api/reservations/" + ApiSupport.unknownId());
    }

    @When("the lifecycle client deletes a reservation id that was never created")
    public void deleteUnknown() {
        response = Harness.authed().delete("/api/reservations/" + ApiSupport.unknownId());
    }

    @Then("the lifecycle response status is {int}")
    public void statusIs(int expected) {
        assertThat(response.statusCode()).as("status, body: %s", response.asString()).isEqualTo(expected);
    }

    @Then("the lifecycle response status is successful")
    public void statusIsSuccessful() {
        assertThat(response.statusCode()).as("status, body: %s", response.asString()).isBetween(200, 299);
    }

    @Then("the lifecycle response status is a client error")
    public void statusIsClientError() {
        assertThat(response.statusCode()).as("status, body: %s", response.asString()).isBetween(400, 499);
    }

    @Then("the fetched reservation matches the submitted pet name and owner email")
    public void matchesSubmitted() {
        assertThat(response.jsonPath().getString("petName")).isEqualTo(body.get("petName"));
        assertThat(response.jsonPath().getString("ownerEmail")).isEqualTo(body.get("ownerEmail"));
    }

    @Then("the fetched reservation has promo code {string}")
    public void hasPromoCode(String promo) {
        assertThat(response.jsonPath().getString("promoCode")).isEqualTo(promo);
    }

    @Then("the fetched reservation shows the updated pet name and {int} nights")
    public void showsUpdate(int nights) {
        assertThat(response.jsonPath().getString("petName")).isEqualTo(updatedPetName);
        assertThat(response.jsonPath().getInt("nights")).isEqualTo(nights);
    }
}
