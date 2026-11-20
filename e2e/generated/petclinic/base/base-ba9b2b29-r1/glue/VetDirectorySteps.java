package glue;

import static org.assertj.core.api.Assertions.assertThat;

import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

public class VetDirectorySteps {

    private Response response;

    @When("the vet directory is requested")
    public void theVetDirectoryIsRequested() {
        response = Harness.authed().get("/api/vets");
    }

    @Then("the vet directory responds with status {int}")
    public void theVetDirectoryRespondsWithStatus(int status) {
        assertThat(response.statusCode()).as("response: " + response.asString()).isEqualTo(status);
    }
}
