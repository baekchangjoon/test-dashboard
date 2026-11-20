package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiData;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.LinkedHashMap;
import java.util.Map;
import td.harness.Harness;

public class ReservationLifecycleSteps {
    private Map<String, Object> request;
    private Response response;
    private Integer reservationId;

    @Given("a valid boarding reservation request with a unique pet name")
    public void validRequest() {
        request = ApiData.reservationBody();
    }

    @Given("the boarding reservation request uses promo code {string}")
    public void promoCode(String code) {
        request.put("promoCode", code);
    }

    @When("the boarding reservation is submitted")
    public void submit() {
        response = Harness.authed().contentType("application/json").body(request).post("/api/reservations");
        reservationId = ApiData.extractId(response);
    }

    @Then("the boarding reservation is created with an id")
    public void created() {
        assertThat(response.statusCode()).as(response.asString()).isIn(200, 201);
        assertThat(reservationId).isNotNull();
    }

    @Then("reading the boarding reservation by id returns the submitted pet name and nights")
    public void readBack() {
        Response r = Harness.authed().get("/api/reservations/" + reservationId);
        assertThat(r.statusCode()).as(r.asString()).isEqualTo(200);
        assertThat(ApiData.str(r.jsonPath().get("petName"))).isEqualTo(request.get("petName"));
        assertThat(r.jsonPath().getInt("nights")).isEqualTo(request.get("nights"));
    }

    @Given("an existing boarding reservation created through the API")
    public void existing() {
        validRequest();
        submit();
        created();
    }

    @When("the boarding reservation nights are updated to {int}")
    public void updateNights(int nights) {
        Map<String, Object> body = new LinkedHashMap<>(request);
        body.put("nights", nights);
        response = Harness.authed().contentType("application/json").body(body).put("/api/reservations/" + reservationId);
    }

    @Then("the boarding reservation update succeeds")
    public void updateSucceeds() {
        assertThat(response.statusCode()).as(response.asString()).isIn(200, 204);
    }

    @Then("reading the boarding reservation by id shows {int} nights")
    public void readNights(int nights) {
        Response r = Harness.authed().get("/api/reservations/" + reservationId);
        assertThat(r.statusCode()).as(r.asString()).isEqualTo(200);
        assertThat(r.jsonPath().getInt("nights")).isEqualTo(nights);
    }

    @When("the boarding reservation is deleted")
    public void delete() {
        response = Harness.authed().delete("/api/reservations/" + reservationId);
    }

    @Then("the boarding reservation deletion succeeds")
    public void deleteSucceeds() {
        assertThat(response.statusCode()).as(response.asString()).isIn(200, 204);
    }

    @Then("reading the deleted boarding reservation returns status {int}")
    public void readDeleted(int status) {
        Response r = Harness.authed().get("/api/reservations/" + reservationId);
        assertThat(r.statusCode()).as(r.asString()).isEqualTo(status);
    }
}
