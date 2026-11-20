package glue;

import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

public class PetCatalogSteps {

    private Response response;

    @When("the pet catalog client requests the pet types")
    public void requestTypes() {
        response = Harness.authed().get("/api/pets/types");
    }

    @Then("the pet catalog response status is {int}")
    public void statusIs(int expected) {
        assertThat(response.statusCode()).as("status, body: %s", response.asString()).isEqualTo(expected);
    }

    @Then("the pet catalog response is a JSON list")
    public void isJsonList() {
        List<Object> types = response.jsonPath().getList("$");
        assertThat(types).isNotNull();
    }
}
