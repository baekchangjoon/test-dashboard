package glue;

import static org.assertj.core.api.Assertions.assertThat;

import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

public class PetTypesSteps {

    private Response response;

    @When("the pet type catalogue is requested")
    public void thePetTypeCatalogueIsRequested() {
        response = Harness.authed().get("/api/pets/types");
    }

    @Then("the pet type catalogue is returned successfully")
    public void thePetTypeCatalogueIsReturnedSuccessfully() {
        assertThat(response.statusCode()).as("pet types: %s", response.asString()).isEqualTo(200);
        assertThat(response.asString()).isNotBlank();
    }
}
