package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiData;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.Map;
import td.harness.Harness;

public class ReservationListingSteps {

    private Integer reservationId;
    private Response response;

    @Given("a listed boarding reservation for a unique pet staying {int} nights")
    public void listedReservation(int nights) {
        Map<String, Object> body = ApiData.reservationBody(ApiData.uniqueName("Pet"), nights);
        Response created = ApiData.createReservation(body);
        assertThat(created.statusCode()).as(created.asString()).isBetween(200, 299);
        reservationId = ApiData.extractId(created);
        assertThat(reservationId).isNotNull();
    }

    @When("the client lists boarding reservations without filters")
    public void listWithoutFilters() {
        response = Harness.authed().get("/api/reservations");
    }

    @When("the client lists boarding reservations with minimum nights {int}")
    public void listWithMinNights(int minNights) {
        response = Harness.authed().queryParam("minNights", minNights).get("/api/reservations");
    }

    @When("the client lists only recent boarding reservations")
    public void listRecentOnly() {
        response = Harness.authed().queryParam("recentOnly", true).get("/api/reservations");
    }

    @When("the client lists boarding reservations with price tier {string}")
    public void listWithTier(String tier) {
        response = Harness.authed().queryParam("tier", tier).get("/api/reservations");
    }

    @Then("the boarding reservation list returns status {int}")
    public void listReturnsStatus(int status) {
        assertThat(response.statusCode()).as(response.asString()).isEqualTo(status);
    }

    @Then("the boarding reservation list contains the newly created reservation")
    public void listContainsCreated() {
        assertThat(ApiData.idsInList(response)).contains(String.valueOf(reservationId));
    }

    @Then("the boarding reservation list does not contain the newly created reservation")
    public void listDoesNotContainCreated() {
        assertThat(ApiData.idsInList(response)).doesNotContain(String.valueOf(reservationId));
    }
}
