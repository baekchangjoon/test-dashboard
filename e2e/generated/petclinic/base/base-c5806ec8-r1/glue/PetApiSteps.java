package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.HashMap;
import java.util.Map;
import td.harness.Harness;

public class PetApiSteps {

    private Response lastResponse;

    @When("the client requests the list of pet types")
    public void listPetTypes() {
        lastResponse = Harness.authed().get("/api/pets/types");
    }

    @When("the client fetches a pet with an unknown id")
    public void fetchUnknownPet() {
        lastResponse = Harness.authed().get("/api/pets/" + ApiSupport.UNKNOWN_ID);
    }

    @When("the client updates a pet with an unknown id")
    public void updateUnknownPet() {
        Map<String, Object> body = new HashMap<>();
        body.put("birthDate", "2020-01-01");
        lastResponse = Harness.authed().contentType("application/json").body(body).put("/api/pets/" + ApiSupport.UNKNOWN_ID);
    }

    @Then("the pet response has status {int}")
    public void hasStatus(int status) {
        assertThat(lastResponse.statusCode()).as("body: %s", lastResponse.asString()).isEqualTo(status);
    }

    @Then("the pet types response body is not blank")
    public void bodyNotBlank() {
        assertThat(lastResponse.asString()).isNotBlank();
    }

    @Then("the pet response is a client error")
    public void isClientError() {
        assertThat(lastResponse.statusCode()).as("body: %s", lastResponse.asString()).isBetween(400, 499);
    }
}
