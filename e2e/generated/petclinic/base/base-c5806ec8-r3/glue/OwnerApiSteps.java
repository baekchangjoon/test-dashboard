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

public class OwnerApiSteps {

    private Response response;
    private Map<String, Object> ownerBody;
    private String ownerId;
    private String newCity;

    @When("the owner list is requested")
    public void theOwnerListIsRequested() {
        response = Harness.authed().get("/api/owners");
    }

    @Then("the owner list response has status {int}")
    public void theOwnerListResponseHasStatus(int status) {
        assertThat(response.statusCode()).as("owners: %s", response.asString()).isEqualTo(status);
    }

    @Given("a new owner has been registered through the API")
    public void aNewOwnerHasBeenRegistered() {
        ownerBody = ApiSupport.newOwnerBody();
        Response r = Harness.authed().contentType("application/json").body(ApiSupport.toJson(ownerBody))
                .post("/api/owners");
        assertThat(r.statusCode()).as("create owner: %s", r.asString()).isIn(200, 201);
        ownerId = ApiSupport.extractId(r);
        assertThat(ownerId).as("owner id").isNotBlank();
    }

    @When("the registered owner is fetched by id")
    public void theRegisteredOwnerIsFetchedById() {
        response = Harness.authed().get("/api/owners/" + ownerId);
    }

    @Then("the fetched owner has the submitted city and telephone")
    public void theFetchedOwnerHasTheSubmittedCityAndTelephone() {
        assertThat(response.statusCode()).as("get owner: %s", response.asString()).isEqualTo(200);
        assertThat(response.jsonPath().getString("city")).isEqualTo(ownerBody.get("city"));
        assertThat(response.jsonPath().getString("telephone")).isEqualTo(ownerBody.get("telephone"));
    }

    @When("the registered owner is updated with a new city")
    public void theRegisteredOwnerIsUpdatedWithANewCity() {
        newCity = "Town" + ApiSupport.suffix();
        Map<String, Object> updated = new LinkedHashMap<>(ownerBody);
        updated.put("city", newCity);
        response = Harness.authed().contentType("application/json").body(ApiSupport.toJson(updated))
                .put("/api/owners/" + ownerId);
    }

    @Then("the owner update succeeds")
    public void theOwnerUpdateSucceeds() {
        assertThat(response.statusCode()).as("update owner: %s", response.asString()).isBetween(200, 299);
    }

    @Then("fetching the registered owner shows the new city")
    public void fetchingTheRegisteredOwnerShowsTheNewCity() {
        Response r = Harness.authed().get("/api/owners/" + ownerId);
        assertThat(r.statusCode()).isEqualTo(200);
        assertThat(r.jsonPath().getString("city")).isEqualTo(newCity);
    }
}
