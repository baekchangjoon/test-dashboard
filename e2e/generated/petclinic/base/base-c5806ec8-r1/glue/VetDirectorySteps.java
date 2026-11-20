package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

public class VetDirectorySteps {

    private Response lastResponse;

    @When("the client lists all veterinarians")
    public void listVets() {
        lastResponse = Harness.authed().get("/api/vets");
    }

    @When("the client fetches a veterinarian with an unknown id")
    public void fetchUnknownVet() {
        lastResponse = Harness.authed().get("/api/vets/" + ApiSupport.UNKNOWN_ID);
    }

    @Then("the veterinarian response has status {int}")
    public void hasStatus(int status) {
        assertThat(lastResponse.statusCode()).as("body: %s", lastResponse.asString()).isEqualTo(status);
    }

    @Then("the veterinarian response is a client error")
    public void isClientError() {
        assertThat(lastResponse.statusCode()).as("body: %s", lastResponse.asString()).isBetween(400, 499);
    }
}
