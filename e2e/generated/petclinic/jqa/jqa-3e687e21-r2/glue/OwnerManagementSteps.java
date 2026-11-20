package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiData;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import td.harness.Harness;

public class OwnerManagementSteps {

    private Map<String, Object> payload;
    private Response response;
    private Integer ownerId;
    private String newCity;

    @Given("a unique owner payload is prepared")
    public void aUniqueOwnerPayloadIsPrepared() {
        payload = ApiData.ownerPayload();
    }

    @Given("the owner payload field {string} is blank")
    public void theOwnerPayloadFieldIsBlank(String field) {
        payload.put(field, "");
    }

    @When("the owner payload is posted to the owner API")
    public void theOwnerPayloadIsPosted() {
        response = Harness.authed().contentType("application/json").body(payload).post("/api/owners");
        ownerId = ApiData.extractId(response);
    }

    @Given("an owner has been created through the owner API")
    public void anOwnerHasBeenCreated() {
        aUniqueOwnerPayloadIsPrepared();
        theOwnerPayloadIsPosted();
        assertThat(response.statusCode()).as(ApiData.describe(response)).isBetween(200, 299);
        assertThat(ownerId).as("id of the created owner").isNotNull();
    }

    @When("all owners are requested from the owner API")
    public void allOwnersAreRequested() {
        response = Harness.authed().get("/api/owners");
    }

    @When("the created owner is fetched from the owner API")
    public void theCreatedOwnerIsFetched() {
        response = Harness.authed().get("/api/owners/" + ownerId);
    }

    @When("the created owner city is changed to a new unique value")
    public void theCreatedOwnerCityIsChanged() {
        newCity = "Town" + ApiData.suffix();
        Map<String, Object> update = new HashMap<>(payload);
        update.put("city", newCity);
        response = Harness.authed().contentType("application/json").body(update).put("/api/owners/" + ownerId);
    }

    @When("an owner with an unknown id is fetched from the owner API")
    public void anUnknownOwnerIsFetched() {
        response = Harness.authed().get("/api/owners/" + ApiData.unknownId());
    }

    @Then("the owner API request succeeds")
    public void theOwnerRequestSucceeds() {
        assertThat(response.statusCode()).as(ApiData.describe(response)).isBetween(200, 299);
    }

    @Then("the owner API response carries an identifier")
    public void theOwnerResponseCarriesAnIdentifier() {
        assertThat(ownerId).as(ApiData.describe(response)).isNotNull();
    }

    @Then("the fetched owner matches the submitted names, address, city and telephone")
    public void theFetchedOwnerMatches() {
        assertThat(response.jsonPath().getString("firstName")).isEqualTo(payload.get("firstName"));
        assertThat(response.jsonPath().getString("lastName")).isEqualTo(payload.get("lastName"));
        assertThat(response.jsonPath().getString("address")).isEqualTo(payload.get("address"));
        assertThat(response.jsonPath().getString("city")).isEqualTo(payload.get("city"));
        assertThat(response.jsonPath().getString("telephone")).isEqualTo(payload.get("telephone"));
    }

    @Then("the owner fetched again has the new city")
    public void theOwnerFetchedAgainHasNewCity() {
        Response fetched = Harness.authed().get("/api/owners/" + ownerId);
        assertThat(fetched.statusCode()).as(ApiData.describe(fetched)).isBetween(200, 299);
        assertThat(fetched.jsonPath().getString("city")).isEqualTo(newCity);
    }

    @Then("the owner list contains the created owner")
    public void theOwnerListContainsCreated() {
        List<Object> ids = response.jsonPath().getList("id");
        assertThat(ApiData.listContainsId(ids, ownerId)).as("owner list contains id " + ownerId).isTrue();
    }

    @Then("the owner API request is rejected with a client error")
    public void theOwnerRequestIsRejected() {
        assertThat(response.statusCode()).as(ApiData.describe(response)).isBetween(400, 499);
    }
}
