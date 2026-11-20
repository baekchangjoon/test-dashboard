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

public class OwnerManagementSteps {

    private Map<String, Object> submitted;
    private String ownerId;
    private String newCity;
    private Response response;

    @Given("a new owner has been registered via the owner API")
    public void ownerRegistered() {
        submitted = ApiSupport.newOwnerBody();
        Response created = Harness.authed().contentType("application/json").body(submitted).post("/api/owners");
        assertThat(created.statusCode()).as("create owner: %s", created.asString()).isBetween(200, 299);
        ownerId = ApiSupport.extractId(created);
        assertThat(ownerId).isNotBlank();
    }

    @When("the registered owner is fetched by id")
    public void fetchOwner() {
        response = Harness.authed().get("/api/owners/" + ownerId);
    }

    @Then("the owner response status is {int}")
    public void ownerStatusIs(int expected) {
        assertThat(response.statusCode()).as("response body: %s", response.asString()).isEqualTo(expected);
    }

    @Then("the fetched owner has the submitted first name, last name and city")
    public void fetchedOwnerMatches() {
        assertThat(response.jsonPath().getString("firstName")).isEqualTo(submitted.get("firstName"));
        assertThat(response.jsonPath().getString("lastName")).isEqualTo(submitted.get("lastName"));
        assertThat(response.jsonPath().getString("city")).isEqualTo(submitted.get("city"));
    }

    @When("all owners are listed via the owner API")
    public void listOwners() {
        response = Harness.authed().get("/api/owners");
    }

    @Then("the owner list response body is a JSON document")
    public void ownerListIsJson() {
        assertThat(ApiSupport.looksLikeJson(response.asString())).as("body: %s", response.asString()).isTrue();
    }

    @When("the city of the registered owner is changed to a new value")
    public void changeCity() {
        newCity = "Newtown" + ApiSupport.letters(6);
        Map<String, Object> body = new HashMap<>(submitted);
        body.put("id", Integer.valueOf(ownerId));
        body.put("city", newCity);
        response = Harness.authed().contentType("application/json").body(body).put("/api/owners/" + ownerId);
    }

    @Then("the owner update succeeds")
    public void ownerUpdateSucceeds() {
        assertThat(response.statusCode()).as("response body: %s", response.asString()).isBetween(200, 299);
    }

    @Then("fetching the registered owner shows the new city")
    public void fetchShowsNewCity() {
        Response fetched = Harness.authed().get("/api/owners/" + ownerId);
        assertThat(fetched.statusCode()).isEqualTo(200);
        assertThat(fetched.jsonPath().getString("city")).isEqualTo(newCity);
    }

    @When("an unknown owner id is fetched via the owner API")
    public void fetchUnknownOwner() {
        response = Harness.authed().get("/api/owners/" + ApiSupport.UNKNOWN_ID);
    }

    @When("an owner is registered with the invalid variant {string}")
    public void registerInvalidOwner(String variant) {
        Map<String, Object> body = ApiSupport.newOwnerBody();
        switch (variant) {
            case "missing first name":
                body.remove("firstName");
                break;
            case "non numeric telephone":
                body.put("telephone", "phone" + ApiSupport.letters(4));
                break;
            default:
                throw new IllegalArgumentException("Unknown variant: " + variant);
        }
        response = Harness.authed().contentType("application/json").body(body).post("/api/owners");
    }
}
