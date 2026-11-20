package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiData;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.List;
import td.harness.Harness;

public class VetDirectorySteps {

    private Response response;
    private Response listResponse;
    private Object firstVetId;

    @When("the veterinarian list is requested")
    public void theVetListIsRequested() {
        response = Harness.authed().get("/api/vets");
    }

    @Given("the veterinarian list has been retrieved")
    public void theVetListHasBeenRetrieved() {
        listResponse = Harness.authed().get("/api/vets");
        assertThat(listResponse.statusCode()).as(ApiData.describe(listResponse)).isBetween(200, 299);
        List<Object> ids = listResponse.jsonPath().getList("id");
        firstVetId = (ids == null || ids.isEmpty()) ? null : ids.get(0);
    }

    @When("the first listed veterinarian is fetched by id if any exists")
    public void theFirstVetIsFetched() {
        if (firstVetId != null) {
            response = Harness.authed().get("/api/vets/" + firstVetId);
        }
    }

    @When("a veterinarian with an unknown id is requested")
    public void anUnknownVetIsRequested() {
        response = Harness.authed().get("/api/vets/" + ApiData.unknownId());
    }

    @Then("the veterinarian request succeeds")
    public void theVetRequestSucceeds() {
        assertThat(response.statusCode()).as(ApiData.describe(response)).isBetween(200, 299);
    }

    @Then("the veterinarian list response is a list")
    public void theVetListIsAList() {
        List<Object> items = response.jsonPath().getList("$");
        assertThat(items).isNotNull();
    }

    @Then("the individually fetched veterinarian matches the listed one")
    public void theFetchedVetMatches() {
        if (firstVetId == null) {
            List<Object> items = listResponse.jsonPath().getList("$");
            assertThat(items).isEmpty();
            return;
        }
        assertThat(response.statusCode()).as(ApiData.describe(response)).isBetween(200, 299);
        Object fetchedId = response.jsonPath().get("id");
        assertThat(String.valueOf(fetchedId)).isEqualTo(String.valueOf(firstVetId));
    }

    @Then("the veterinarian request is rejected with a client error")
    public void theVetRequestIsRejected() {
        assertThat(response.statusCode()).as(ApiData.describe(response)).isBetween(400, 499);
    }
}
