package glue;

import static org.assertj.core.api.Assertions.assertThat;

import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

public class PetTypesSteps {

    private Response response;

    @When("the pet types are requested")
    public void thePetTypesAreRequested() {
        response = Harness.authed().get("/api/pets/types");
    }

    @Then("the pet types request responds with status {int} and a body")
    public void thePetTypesRequestRespondsWithStatusAndABody(int status) {
        assertThat(response.statusCode()).as("response: " + response.asString()).isEqualTo(status);
        assertThat(response.asString()).isNotBlank();
    }
}
