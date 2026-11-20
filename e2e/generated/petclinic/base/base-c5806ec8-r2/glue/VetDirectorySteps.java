package glue;

import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

import static org.assertj.core.api.Assertions.assertThat;

public class VetDirectorySteps {

    private Response response;

    @When("the vet directory client requests the vet list")
    public void requestVets() {
        response = Harness.authed().get("/api/vets");
    }

    @Then("the vet directory response status is {int}")
    public void statusIs(int expected) {
        assertThat(response.statusCode()).as("status, body: %s", response.asString()).isEqualTo(expected);
    }

    @Then("the vet directory response body is not empty")
    public void bodyNotEmpty() {
        assertThat(response.asString()).isNotBlank();
    }
}
