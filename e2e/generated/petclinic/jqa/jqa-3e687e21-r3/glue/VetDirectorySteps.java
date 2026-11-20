package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiData;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.List;
import td.harness.Harness;

public class VetDirectorySteps {

    private Response response;
    private Response listResponse;
    private Response vetResponse;
    private String vetId;

    @When("the client lists all veterinarians")
    public void listVets() {
        listResponse = Harness.authed().get("/api/vets");
        response = listResponse;
    }

    @When("the client fetches the first listed veterinarian if any exists")
    public void fetchFirstVet() {
        assertThat(listResponse.statusCode()).isEqualTo(200);
        List<String> ids = ApiData.idsInList(listResponse);
        if (!ids.isEmpty()) {
            vetId = ids.get(0);
            vetResponse = Harness.authed().get("/api/vets/" + vetId);
        }
    }

    @When("the client fetches a veterinarian with an id that does not exist")
    public void fetchUnknownVet() {
        response = Harness.authed().get("/api/vets/987654321");
    }

    @Then("the veterinarian response has status {int}")
    public void vetResponseStatus(int status) {
        assertThat(response.statusCode()).as(response.asString()).isEqualTo(status);
    }

    @Then("the veterinarian list is a JSON document")
    public void vetListIsJson() {
        String body = response.asString().trim();
        assertThat(body.startsWith("[") || body.startsWith("{")).as(body).isTrue();
    }

    @Then("the veterinarian lookup succeeds for the fetched veterinarian")
    public void vetLookupSucceeds() {
        assertThat(listResponse.statusCode()).isEqualTo(200);
        if (vetResponse != null) {
            assertThat(vetResponse.statusCode()).as(vetResponse.asString()).isEqualTo(200);
            assertThat(String.valueOf(ApiData.extractId(vetResponse))).isEqualTo(vetId);
        }
    }
}
