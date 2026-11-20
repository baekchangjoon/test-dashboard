package glue;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

public class VetDirectorySteps {

    private Response response;
    private Response listResponse;
    private String vetId;

    @When("the vet directory is listed")
    public void listVets() {
        response = Harness.authed().get("/api/vets");
    }

    @Then("the vet response status is {int}")
    public void vetStatusIs(int expected) {
        assertThat(response.statusCode()).as("response body: %s", response.asString()).isEqualTo(expected);
    }

    @Then("the vet directory payload is a JSON document")
    public void vetPayloadIsJson() {
        assertThat(ApiSupport.looksLikeJson(response.asString())).as("body: %s", response.asString()).isTrue();
    }

    @Given("the vet directory has been listed")
    public void vetDirectoryListed() {
        listResponse = Harness.authed().get("/api/vets");
        assertThat(listResponse.statusCode()).isEqualTo(200);
        List<Map<String, Object>> items = ApiSupport.listItems(listResponse);
        if (!items.isEmpty() && items.get(0).get("id") != null) {
            vetId = String.valueOf(items.get(0).get("id"));
        }
    }

    @When("the first listed vet is fetched by id")
    public void fetchFirstVet() {
        if (vetId != null) {
            response = Harness.authed().get("/api/vets/" + vetId);
        } else {
            response = listResponse;
        }
    }

    @Then("the fetched vet matches the first listed vet")
    public void fetchedVetMatches() {
        assertThat(response.statusCode()).as("response body: %s", response.asString()).isEqualTo(200);
        if (vetId != null) {
            assertThat(String.valueOf(response.jsonPath().get("id").toString())).isEqualTo(vetId);
        }
    }

    @When("an unknown vet id is fetched")
    public void fetchUnknownVet() {
        response = Harness.authed().get("/api/vets/" + ApiSupport.UNKNOWN_ID);
    }
}
