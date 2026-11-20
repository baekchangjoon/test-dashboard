package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiData;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.List;
import td.harness.Harness;

public class PetCatalogSteps {

    private Response response;

    @When("the pet types are requested from the pet API")
    public void thePetTypesAreRequested() {
        response = Harness.authed().get("/api/pets/types");
    }

    @When("a pet with an unknown id is requested from the pet API")
    public void anUnknownPetIsRequested() {
        response = Harness.authed().get("/api/pets/" + ApiData.unknownId());
    }

    @Then("the pet API request succeeds")
    public void thePetRequestSucceeds() {
        assertThat(response.statusCode()).as(ApiData.describe(response)).isBetween(200, 299);
    }

    @Then("the pet types response is a list")
    public void thePetTypesResponseIsAList() {
        List<Object> items = response.jsonPath().getList("$");
        assertThat(items).isNotNull();
    }

    @Then("every listed pet type has a non-empty name")
    public void everyPetTypeHasAName() {
        List<Object> names = response.jsonPath().getList("name");
        assertThat(names).isNotNull();
        for (Object name : names) {
            assertThat(name).isNotNull();
            assertThat(String.valueOf(name)).isNotBlank();
        }
    }

    @Then("the pet API request is rejected with a client error")
    public void thePetRequestIsRejected() {
        assertThat(response.statusCode()).as(ApiData.describe(response)).isBetween(400, 499);
    }
}
