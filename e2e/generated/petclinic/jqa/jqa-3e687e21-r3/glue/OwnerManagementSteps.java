package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiData;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.HashMap;
import java.util.Map;
import td.harness.Harness;

public class OwnerManagementSteps {

    private Map<String, Object> ownerBody;
    private Integer ownerId;
    private String newCity;
    private Response response;

    @Given("a newly registered owner with a unique name")
    public void newlyRegisteredOwner() {
        ownerBody = ApiData.ownerBody(ApiData.uniqueName("Ann"), ApiData.uniqueName("Lee"),
                ApiData.uniqueName("City"), ApiData.phoneDigits());
        Response created = ApiData.postOwner(ownerBody);
        assertThat(created.statusCode()).as(created.asString()).isBetween(200, 299);
        ownerId = ApiData.extractId(created);
        assertThat(ownerId).as("created owner id").isNotNull();
    }

    @When("the client fetches that owner by id")
    public void fetchThatOwner() {
        response = Harness.authed().get("/api/owners/" + ownerId);
    }

    @When("the client lists all owners")
    public void listOwners() {
        response = Harness.authed().get("/api/owners");
    }

    @When("the client changes that owner's city to a new unique city")
    public void changeCity() {
        newCity = ApiData.uniqueName("Town");
        Map<String, Object> update = new HashMap<>(ownerBody);
        update.put("city", newCity);
        response = Harness.authed().contentType("application/json").body(update).put("/api/owners/" + ownerId);
    }

    @When("the client registers an owner whose {string} is {string}")
    public void registerInvalidOwner(String field, String value) {
        Map<String, Object> body = ApiData.ownerBody(ApiData.uniqueName("Ann"), ApiData.uniqueName("Lee"),
                ApiData.uniqueName("City"), ApiData.phoneDigits());
        body.put(field, value);
        response = ApiData.postOwner(body);
    }

    @When("the client fetches an owner with an id that does not exist")
    public void fetchUnknownOwner() {
        response = Harness.authed().get("/api/owners/987654321");
    }

    @Then("the owner response has status {int}")
    public void ownerResponseStatus(int status) {
        assertThat(response.statusCode()).as(response.asString()).isEqualTo(status);
    }

    @Then("the fetched owner matches the registered first name, last name and city")
    public void fetchedOwnerMatches() {
        assertThat(response.jsonPath().getString("firstName")).isEqualTo(ownerBody.get("firstName"));
        assertThat(response.jsonPath().getString("lastName")).isEqualTo(ownerBody.get("lastName"));
        assertThat(response.jsonPath().getString("city")).isEqualTo(ownerBody.get("city"));
    }

    @Then("the owner list contains the newly registered owner")
    public void ownerListContainsNew() {
        assertThat(ApiData.idsInList(response)).contains(String.valueOf(ownerId));
    }

    @Then("the owner update succeeds")
    public void ownerUpdateSucceeds() {
        assertThat(response.statusCode()).as(response.asString()).isBetween(200, 299);
    }

    @Then("fetching that owner shows the new city")
    public void fetchingShowsNewCity() {
        Response read = Harness.authed().get("/api/owners/" + ownerId);
        assertThat(read.statusCode()).isEqualTo(200);
        assertThat(read.jsonPath().getString("city")).isEqualTo(newCity);
    }
}
