package glue;

import glue.support.ApiData;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.HashMap;
import java.util.Map;
import td.harness.Harness;

import static org.assertj.core.api.Assertions.assertThat;

public class ReservationLifecycleSteps {

    private Response response;
    private Map<String, Object> body;
    private String reservationId;

    @Given("a boarding reservation has been created with unique data")
    public void createReservation() {
        body = ApiData.reservationBody();
        Response r = Harness.authed().contentType("application/json").body(body).post("/api/reservations");
        assertThat(r.statusCode()).isIn(200, 201);
        reservationId = ApiData.extractId(r);
        assertThat(reservationId).isNotBlank();
    }

    @When("the client retrieves the created boarding reservation")
    public void retrieveCreated() {
        response = Harness.authed().get("/api/reservations/" + reservationId);
    }

    @Then("the reservation API responds with status {int}")
    public void reservationStatus(int code) {
        assertThat(response.statusCode()).isEqualTo(code);
    }

    @Then("the retrieved reservation shows the submitted pet name and owner email")
    public void retrievedFields() {
        assertThat(response.jsonPath().getString("petName")).isEqualTo(body.get("petName"));
        assertThat(response.jsonPath().getString("ownerEmail")).isEqualTo(body.get("ownerEmail"));
    }

    @When("the client creates a boarding reservation using promo code {string}")
    public void createWithPromo(String promo) {
        body = ApiData.reservationBody();
        body.put("promoCode", promo);
        response = Harness.authed().contentType("application/json").body(body).post("/api/reservations");
    }

    @Then("the promo reservation is created successfully")
    public void promoCreated() {
        assertThat(response.statusCode()).isIn(200, 201);
        assertThat(ApiData.extractId(response)).isNotBlank();
    }

    @When("the client changes the nights of the created boarding reservation to {int}")
    public void changeNights(int nights) {
        Map<String, Object> update = new HashMap<>(body);
        update.put("nights", nights);
        response = Harness.authed().contentType("application/json").body(update).put("/api/reservations/" + reservationId);
    }

    @Then("the reservation update is accepted")
    public void updateAccepted() {
        assertThat(response.statusCode()).isIn(200, 204);
    }

    @Then("retrieving the created boarding reservation shows {int} nights")
    public void retrievedNights(int nights) {
        Response r = Harness.authed().get("/api/reservations/" + reservationId);
        assertThat(r.statusCode()).isEqualTo(200);
        assertThat(r.jsonPath().getInt("nights")).isEqualTo(nights);
    }

    @When("the client deletes the created boarding reservation")
    public void deleteCreated() {
        response = Harness.authed().delete("/api/reservations/" + reservationId);
    }

    @Then("the reservation deletion is accepted")
    public void deletionAccepted() {
        assertThat(response.statusCode()).isIn(200, 202, 204);
    }

    @Then("retrieving the deleted boarding reservation returns status {int}")
    public void retrieveDeleted(int code) {
        Response r = Harness.authed().get("/api/reservations/" + reservationId);
        assertThat(r.statusCode()).isEqualTo(code);
    }

    @When("the client retrieves a boarding reservation with an unknown id")
    public void retrieveUnknown() {
        response = Harness.authed().get("/api/reservations/" + ApiData.unknownId());
    }

    @When("the client updates a boarding reservation with an unknown id")
    public void updateUnknown() {
        response = Harness.authed().contentType("application/json").body(ApiData.reservationBody())
                .put("/api/reservations/" + ApiData.unknownId());
    }

    @When("the client deletes a boarding reservation with an unknown id")
    public void deleteUnknown() {
        response = Harness.authed().delete("/api/reservations/" + ApiData.unknownId());
    }
}
