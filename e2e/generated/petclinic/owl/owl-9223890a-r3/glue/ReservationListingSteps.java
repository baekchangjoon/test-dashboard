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
    private Integer createdId;
    private Response response;

    @Given("a boarding reservation with {int} nights has been created for listing")
    public void createForListing(int nights) {
        Map<String, Object> body = ApiData.reservationBody();
        body.put("nights", nights);
        Response r = Harness.authed().contentType("application/json").body(body).post("/api/reservations");
        assertThat(r.statusCode()).as(r.asString()).isIn(200, 201);
        createdId = ApiData.extractId(r);
        assertThat(createdId).isNotNull();
    }

    @When("all boarding reservations are listed")
    public void listAll() {
        response = Harness.authed().get("/api/reservations");
    }

    @When("boarding reservations are listed with query parameter {string} set to {string}")
    public void listWithParam(String name, String value) {
        response = Harness.authed().queryParam(name, value).get("/api/reservations");
    }

    @Then("the reservation listing response status is {int}")
    public void status(int expected) {
        assertThat(response.statusCode()).as(response.asString()).isEqualTo(expected);
    }

    @Then("the reservation listing contains the created reservation")
    public void containsCreated() {
        assertThat(ApiData.ids(response)).contains(createdId);
    }

    @Then("every listed reservation has at least {int} nights")
    public void minimumNights(int min) {
        List<Object> nights = ApiData.fieldValues(response, "nights");
        assertThat(nights).isNotEmpty();
        for (Object n : nights) {
            assertThat(Integer.parseInt(String.valueOf(n))).isGreaterThanOrEqualTo(min);
        }
    }
}
