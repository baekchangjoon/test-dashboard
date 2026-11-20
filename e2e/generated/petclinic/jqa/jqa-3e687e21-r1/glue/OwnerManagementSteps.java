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

public class OwnerManagementSteps {

    private Response response;
    private Map<String, Object> ownerBody;
    private String ownerId;
    private String newCity;

    @When("the client requests the owner list")
    public void requestOwnerList() {
        response = Harness.authed().get("/api/owners");
    }

    @Given("a new owner has been registered with unique data")
    public void registerOwner() {
        ownerBody = ApiData.ownerBody();
        Response r = Harness.authed().contentType("application/json").body(ownerBody).post("/api/owners");
        assertThat(r.statusCode()).isIn(200, 201);
        ownerId = ApiData.extractId(r);
        assertThat(ownerId).isNotBlank();
    }

    @When("the client fetches the registered owner")
    public void fetchOwner() {
        response = Harness.authed().get("/api/owners/" + ownerId);
    }

    @Then("the owner API responds with status {int}")
    public void ownerStatus(int code) {
        assertThat(response.statusCode()).isEqualTo(code);
    }

    @Then("the fetched owner has the registered first name and last name")
    public void fetchedOwnerNames() {
        assertThat(response.jsonPath().getString("firstName")).isEqualTo(ownerBody.get("firstName"));
        assertThat(response.jsonPath().getString("lastName")).isEqualTo(ownerBody.get("lastName"));
    }

    @When("the client updates the registered owner city to a new unique value")
    public void updateOwnerCity() {
        newCity = "City" + ApiData.letters();
        Map<String, Object> body = new HashMap<>(ownerBody);
        body.put("city", newCity);
        response = Harness.authed().contentType("application/json").body(body).put("/api/owners/" + ownerId);
    }

    @Then("the owner update is accepted")
    public void ownerUpdateAccepted() {
        assertThat(response.statusCode()).isIn(200, 204);
    }

    @Then("fetching the registered owner shows the new city")
    public void fetchShowsNewCity() {
        Response r = Harness.authed().get("/api/owners/" + ownerId);
        assertThat(r.statusCode()).isEqualTo(200);
        assertThat(r.jsonPath().getString("city")).isEqualTo(newCity);
    }

    @When("the client registers an owner with blank {string}")
    public void registerOwnerWithBlank(String field) {
        Map<String, Object> body = ApiData.ownerBody();
        body.put(field, "");
        response = Harness.authed().contentType("application/json").body(body).post("/api/owners");
    }

    @When("the client registers an owner with telephone {string}")
    public void registerOwnerWithTelephone(String telephone) {
        Map<String, Object> body = ApiData.ownerBody();
        body.put("telephone", telephone);
        response = Harness.authed().contentType("application/json").body(body).post("/api/owners");
    }

    @When("the client fetches an owner with an unknown id")
    public void fetchUnknownOwner() {
        response = Harness.authed().get("/api/owners/" + ApiData.unknownId());
    }

    @Then("the owner lookup fails with a client error")
    public void ownerLookupFails() {
        assertThat(response.statusCode()).isBetween(400, 499);
    }
}
