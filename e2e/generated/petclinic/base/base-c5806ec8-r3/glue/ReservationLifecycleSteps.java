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

    private Map<String, Object> body;
    private String id;
    private Response response;

    private void create() {
        Response r = ApiSupport.createReservation(body);
        assertThat(r.statusCode()).as("create reservation: %s", r.asString()).isIn(200, 201);
        id = ApiSupport.extractId(r);
        assertThat(id).as("reservation id").isNotBlank();
    }

    @Given("a new boarding reservation has been created")
    public void aNewBoardingReservationHasBeenCreated() {
        body = ApiSupport.newReservationBody();
        create();
    }

    @Given("a boarding reservation with promo code {string} has been created")
    public void aBoardingReservationWithPromoCodeHasBeenCreated(String code) {
        body = ApiSupport.newReservationBody();
        body.put("promoCode", code);
        create();
    }

    @When("the boarding reservation is fetched by its id")
    public void theBoardingReservationIsFetchedByItsId() {
        response = Harness.authed().get("/api/reservations/" + id);
    }

    @Then("the fetched boarding reservation matches the submitted pet name and owner email")
    public void theFetchedBoardingReservationMatches() {
        assertThat(response.statusCode()).as("get reservation: %s", response.asString()).isEqualTo(200);
        assertThat(response.jsonPath().getString("petName")).isEqualTo(body.get("petName"));
        assertThat(response.jsonPath().getString("ownerEmail")).isEqualTo(body.get("ownerEmail"));
    }

    @Then("the boarding reservation fetch returns status {int}")
    public void theBoardingReservationFetchReturnsStatus(int status) {
        assertThat(response.statusCode()).as("get reservation: %s", response.asString()).isEqualTo(status);
    }

    @When("the boarding reservation is updated to {int} nights")
    public void theBoardingReservationIsUpdatedToNights(int nights) {
        Map<String, Object> updated = new LinkedHashMap<>(body);
        updated.put("nights", nights);
        response = Harness.authed().contentType("application/json").body(ApiSupport.toJson(updated))
                .put("/api/reservations/" + id);
    }

    @Then("the boarding reservation update succeeds")
    public void theBoardingReservationUpdateSucceeds() {
        assertThat(response.statusCode()).as("update reservation: %s", response.asString()).isBetween(200, 299);
    }

    @Then("fetching the boarding reservation shows {int} nights")
    public void fetchingTheBoardingReservationShowsNights(int nights) {
        Response r = Harness.authed().get("/api/reservations/" + id);
        assertThat(r.statusCode()).isEqualTo(200);
        assertThat(r.jsonPath().getInt("nights")).isEqualTo(nights);
    }

    @When("the boarding reservation is deleted")
    public void theBoardingReservationIsDeleted() {
        response = Harness.authed().delete("/api/reservations/" + id);
    }

    @Then("the boarding reservation deletion succeeds")
    public void theBoardingReservationDeletionSucceeds() {
        assertThat(response.statusCode()).as("delete reservation: %s", response.asString()).isBetween(200, 299);
    }

    @Then("fetching the deleted boarding reservation returns status {int}")
    public void fetchingTheDeletedBoardingReservationReturnsStatus(int status) {
        Response r = Harness.authed().get("/api/reservations/" + id);
        assertThat(r.statusCode()).isEqualTo(status);
    }

    @When("the boarding reservation list is requested")
    public void theBoardingReservationListIsRequested() {
        response = Harness.authed().get("/api/reservations");
    }

    @Then("the boarding reservation list contains the created pet name")
    public void theBoardingReservationListContainsTheCreatedPetName() {
        assertThat(response.statusCode()).isEqualTo(200);
        assertThat(response.asString()).contains(String.valueOf(body.get("petName")));
    }

    @When("the boarding reservation list is requested with query parameter {string} set to {string}")
    public void theBoardingReservationListIsRequestedWithQueryParameter(String param, String value) {
        response = Harness.authed().queryParam(param, value).get("/api/reservations");
    }

    @Then("the boarding reservation list request returns status {int}")
    public void theBoardingReservationListRequestReturnsStatus(int status) {
        assertThat(response.statusCode()).as("list reservations: %s", response.asString()).isEqualTo(status);
    }
}
