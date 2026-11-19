package glue;

import static org.assertj.core.api.Assertions.assertThat;

import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

public class VetLookupSteps {

    private Response response;

    @When("I list all vets")
    public void listAllVets() {
        response = Harness.authed().get("/api/vets");
    }

    @Then("the vet response status is {int}")
    public void statusIs(int expected) {
        assertThat(response.statusCode()).isEqualTo(expected);
    }
}
