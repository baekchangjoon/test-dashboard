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

public class OwnerManagementSteps {
    private Map<String, Object> owner;
    private Response response;
    private Integer ownerId;
    private String newCity;

    private static Response postOwner(Map<String, Object> body) {
        return Harness.authed().contentType("application/json").body(body).post("/api/owners");
    }

    private Response putOwner(Map<String, Object> body) {
        return Harness.authed().contentType("application/json").body(body).put("/api/owners/" + ownerId);
    }

    @Given("a new owner payload with unique names")
    public void newPayload() {
        owner = ApiData.ownerBody();
    }

    @When("the owner payload is submitted")
    public void submit() {
        response = postOwner(owner);
        ownerId = ApiData.extractId(response);
    }

    @Then("the owner is created with an id")
    public void created() {
        assertThat(response.statusCode()).as(response.asString()).isIn(200, 201);
        assertThat(ownerId).isNotNull();
    }

    @Then("reading the owner by id returns the submitted names, city and telephone")
    public void readBack() {
        Response r = Harness.authed().get("/api/owners/" + ownerId);
        assertThat(r.statusCode()).as(r.asString()).isEqualTo(200);
        assertThat(ApiData.str(r.jsonPath().get("firstName"))).isEqualTo(owner.get("firstName"));
        assertThat(ApiData.str(r.jsonPath().get("lastName"))).isEqualTo(owner.get("lastName"));
        assertThat(ApiData.str(r.jsonPath().get("city"))).isEqualTo(owner.get("city"));
        assertThat(ApiData.str(r.jsonPath().get("telephone"))).isEqualTo(owner.get("telephone"));
    }

    @Given("an existing owner created through the owner API")
    public void existingOwner() {
        newPayload();
        submit();
        created();
    }

    @When("all owners are listed")
    public void listAll() {
        response = Harness.authed().get("/api/owners");
    }

    @Then("the owner listing response is successful and not empty")
    public void listingOk() {
        assertThat(response.statusCode()).as(response.asString()).isEqualTo(200);
        String body = response.asString().trim();
        assertThat(body).isNotEmpty();
        assertThat(body).isNotEqualTo("[]");
    }

    @When("the city of the owner is changed to a unique value")
    public void changeCity() {
        newCity = "City" + ApiData.letters(8);
        Map<String, Object> body = new LinkedHashMap<>(owner);
        body.put("id", ownerId);
        body.put("city", newCity);
        response = putOwner(body);
    }

    @Then("the owner update succeeds")
    public void updateSucceeds() {
        assertThat(response.statusCode()).as(response.asString()).isIn(200, 204);
    }

    @Then("reading the owner by id shows the new city")
    public void readNewCity() {
        Response r = Harness.authed().get("/api/owners/" + ownerId);
        assertThat(r.statusCode()).as(r.asString()).isEqualTo(200);
        assertThat(ApiData.str(r.jsonPath().get("city"))).isEqualTo(newCity);
    }

    @When("the owner payload field {string} is set to {string} and submitted")
    public void invalidField(String field, String value) {
        owner.put(field, value);
        response = postOwner(owner);
    }

    @Then("the owner request is rejected with a client error")
    public void clientError() {
        assertThat(response.statusCode()).as(response.asString()).isBetween(400, 499);
    }

    @When("the owner with id {int} is requested")
    public void getUnknown(int id) {
        response = Harness.authed().get("/api/owners/" + id);
    }

    @When("the existing owner is updated with a blank last name")
    public void blankLastName() {
        Map<String, Object> body = new LinkedHashMap<>(owner);
        body.put("id", ownerId);
        body.put("lastName", "");
        response = putOwner(body);
    }
}
