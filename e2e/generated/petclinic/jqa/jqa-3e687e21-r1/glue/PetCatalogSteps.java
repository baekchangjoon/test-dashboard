package glue;

import glue.support.ApiData;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

import static org.assertj.core.api.Assertions.assertThat;

public class PetCatalogSteps {

    private Response response;

    @When("the client requests the pet type catalog")
    public void requestPetTypes() {
        response = Harness.authed().get("/api/pets/types");
    }

    @Then("the pet API responds with status {int}")
    public void petStatus(int code) {
        assertThat(response.statusCode()).isEqualTo(code);
    }

    @Then("the pet type catalog is returned as a JSON body")
    public void petTypesJson() {
        assertThat(response.contentType()).contains("json");
        assertThat(response.asString()).isNotBlank();
    }

    @When("the client requests a pet with an unknown id")
    public void requestUnknownPet() {
        response = Harness.authed().get("/api/pets/" + ApiData.unknownId());
    }

    @Then("the pet lookup fails with a client error")
    public void petLookupFails() {
        assertThat(response.statusCode()).isBetween(400, 499);
    }
}
