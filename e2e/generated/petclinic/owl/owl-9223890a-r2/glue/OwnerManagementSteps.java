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

public class OwnerManagementSteps {

    private Map<String, Object> owner;
    private String ownerId;
    private String newCity;
    private Response response;

    @Given("a new owner has been registered through the owner API")
    public void registerOwner() {
        owner = ApiSupport.ownerBody();
        Response created = ApiSupport.postJson("/api/owners", owner);
        assertThat(created.statusCode()).as("create response: %s", created.asString()).isIn(200, 201);
        ownerId = ApiSupport.extractId(created);
        assertThat(ownerId).isNotBlank();
    }

    @When("the registered owner is fetched by id")
    public void fetchOwner() {
        response = Harness.authed().get("/api/owners/" + ownerId);
    }

    @Then("the owner API response status is {int}")
    public void statusIs(int expected) {
        assertThat(response.statusCode()).as(response.asString()).isEqualTo(expected);
    }

    @Then("the fetched owner shows the submitted names and city")
    public void ownerShowsFields() {
        assertThat(response.jsonPath().getString("firstName")).isEqualTo(owner.get("firstName"));
        assertThat(response.jsonPath().getString("lastName")).isEqualTo(owner.get("lastName"));
        assertThat(response.jsonPath().getString("city")).isEqualTo(owner.get("city"));
    }

    @When("the city of the registered owner is changed to a new value")
    public void changeCity() {
        newCity = "Newtown" + ApiSupport.randomLetters(6);
        Map<String, Object> updated = new HashMap<>(owner);
        updated.put("city", newCity);
        response = ApiSupport.putJson("/api/owners/" + ownerId, updated);
    }

    @Then("the owner update succeeds")
    public void updateSucceeds() {
        assertThat(response.statusCode()).as(response.asString()).isBetween(200, 299);
    }

    @Then("fetching the registered owner shows the new city")
    public void fetchShowsNewCity() {
        Response fetched = Harness.authed().get("/api/owners/" + ownerId);
        assertThat(fetched.statusCode()).as(fetched.asString()).isEqualTo(200);
        assertThat(fetched.jsonPath().getString("city")).isEqualTo(newCity);
    }

    @When("all owners are listed")
    public void listOwners() {
        response = Harness.authed().get("/api/owners");
    }

    @Then("the owner listing body is not empty")
    public void listingNotEmpty() {
        assertThat(response.asString()).isNotBlank();
    }

    @When("an owner is registered with field {string} set to {string}")
    public void registerInvalid(String field, String value) {
        Map<String, Object> payload = ApiSupport.ownerBody();
        payload.put(field, value);
        response = ApiSupport.postJson("/api/owners", payload);
    }

    @When("an unknown owner id is fetched through the owner API")
    public void fetchUnknownOwner() {
        response = Harness.authed().get("/api/owners/987654321");
    }

    @Then("the owner API response is a client error")
    public void clientError() {
        assertThat(response.statusCode()).as(response.asString()).isBetween(400, 499);
    }
}
