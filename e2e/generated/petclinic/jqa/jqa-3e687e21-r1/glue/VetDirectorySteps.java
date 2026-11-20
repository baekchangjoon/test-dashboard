package glue;

import glue.support.ApiData;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

import static org.assertj.core.api.Assertions.assertThat;

public class VetDirectorySteps {

    private Response response;

    @When("the client requests the veterinarian list")
    public void requestVets() {
        response = Harness.authed().get("/api/vets");
    }

    @Then("the vet API responds with status {int}")
    public void vetStatus(int code) {
        assertThat(response.statusCode()).isEqualTo(code);
    }

    @Then("the veterinarian list is returned as a JSON body")
    public void vetsJson() {
        assertThat(response.contentType()).contains("json");
        assertThat(response.asString()).isNotBlank();
    }

    @When("the client requests a veterinarian with an unknown id")
    public void requestUnknownVet() {
        response = Harness.authed().get("/api/vets/" + ApiData.unknownId());
    }

    @Then("the veterinarian lookup fails with a client error")
    public void vetLookupFails() {
        assertThat(response.statusCode()).isBetween(400, 499);
    }
}
