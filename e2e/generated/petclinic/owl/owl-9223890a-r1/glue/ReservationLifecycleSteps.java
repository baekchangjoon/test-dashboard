package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.LinkedHashMap;
import java.util.Map;
import td.harness.Harness;

public class ReservationLifecycleSteps {

    private Response response;
    private String reservationId;
    private Map<String, Object> bookedBody;

    private Response post(Map<String, Object> body) {
        return Harness.authed().contentType("application/json").body(body).post("/api/reservations");
    }

    private Response readBooked() {
        assertThat(reservationId).as("id of the booked reservation").isNotBlank();
        return Harness.authed().get("/api/reservations/" + reservationId);
    }

    @Given("a new boarding reservation is booked for a uniquely named pet")
    public void aNewReservationIsBooked() {
        bookedBody = ApiSupport.randomReservation(2);
        response = post(bookedBody);
        assertThat(response.statusCode()).as("booking status, body: %s", ApiSupport.text(response)).isIn(200, 201);
        reservationId = ApiSupport.extractId(response);
        assertThat(reservationId).as("id of the booked reservation").isNotBlank();
    }

    @When("the lifecycle client reads the booked reservation")
    public void readsTheBookedReservation() {
        response = readBooked();
    }

    @When("the lifecycle client books a reservation with promo code {string}")
    public void booksWithPromoCode(String promoCode) {
        bookedBody = ApiSupport.randomReservation(2);
        bookedBody.put("promoCode", promoCode);
        response = post(bookedBody);
    }

    @Then("the lifecycle booking succeeds with a generated id")
    public void bookingSucceedsWithId() {
        assertThat(response.statusCode()).as("booking status, body: %s", ApiSupport.text(response)).isIn(200, 201);
        reservationId = ApiSupport.extractId(response);
        assertThat(reservationId).as("generated reservation id").isNotBlank();
    }

    @Then("the booked reservation can be read back with status {int}")
    public void canBeReadBack(int status) {
        Response read = readBooked();
        assertThat(read.statusCode()).as("read status, body: %s", ApiSupport.text(read)).isEqualTo(status);
    }

    @Then("the read reservation shows the booked pet name, room and nights")
    public void readReservationShowsFields() {
        assertThat(ApiSupport.fieldText(response, "petName")).isEqualTo(String.valueOf(bookedBody.get("petName")));
        assertThat(ApiSupport.fieldText(response, "roomNumber")).isEqualTo(String.valueOf(bookedBody.get("roomNumber")));
        assertThat(ApiSupport.fieldText(response, "nights")).isEqualTo(String.valueOf(bookedBody.get("nights")));
    }

    @When("the lifecycle client changes the booked reservation to {int} nights")
    public void changesNights(int nights) {
        Map<String, Object> body = new LinkedHashMap<>(bookedBody);
        body.put("nights", nights);
        response = Harness.authed().contentType("application/json").body(body)
                .put("/api/reservations/" + reservationId);
    }

    @Then("the lifecycle update succeeds")
    public void updateSucceeds() {
        assertThat(ApiSupport.isSuccess(response.statusCode()))
                .as("update status %s, body: %s", response.statusCode(), ApiSupport.text(response)).isTrue();
    }

    @Then("reading the booked reservation shows {int} nights")
    public void readingShowsNights(int nights) {
        Response read = readBooked();
        assertThat(read.statusCode()).isEqualTo(200);
        assertThat(ApiSupport.fieldText(read, "nights")).isEqualTo(String.valueOf(nights));
    }

    @When("the lifecycle client deletes the booked reservation")
    public void deletesTheBookedReservation() {
        assertThat(reservationId).as("id of the booked reservation").isNotBlank();
        response = Harness.authed().delete("/api/reservations/" + reservationId);
    }

    @Then("the lifecycle delete succeeds")
    public void deleteSucceeds() {
        assertThat(ApiSupport.isSuccess(response.statusCode()))
                .as("delete status %s, body: %s", response.statusCode(), ApiSupport.text(response)).isTrue();
    }

    @Then("reading the booked reservation returns status {int}")
    public void readingReturnsStatus(int status) {
        Response read = readBooked();
        assertThat(read.statusCode()).isEqualTo(status);
    }

    @When("the lifecycle client reads reservation id {int}")
    public void readsReservationById(int id) {
        response = Harness.authed().get("/api/reservations/" + id);
    }

    @When("the lifecycle client updates reservation id {int} with valid data")
    public void updatesReservationById(int id) {
        response = Harness.authed().contentType("application/json").body(ApiSupport.randomReservation(2))
                .put("/api/reservations/" + id);
    }

    @When("the lifecycle client deletes reservation id {int}")
    public void deletesReservationById(int id) {
        response = Harness.authed().delete("/api/reservations/" + id);
    }

    @Then("the lifecycle response status is {int}")
    public void responseStatusIs(int status) {
        assertThat(response.statusCode()).as("body: %s", ApiSupport.text(response)).isEqualTo(status);
    }

    @Then("the lifecycle response is a client error")
    public void responseIsClientError() {
        assertThat(ApiSupport.isClientError(response.statusCode()))
                .as("status %s, body: %s", response.statusCode(), ApiSupport.text(response)).isTrue();
    }
}
