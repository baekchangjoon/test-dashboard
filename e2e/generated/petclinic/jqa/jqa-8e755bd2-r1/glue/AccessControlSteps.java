package glue;

import glue.support.ApiSupport;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

import static org.assertj.core.api.Assertions.assertThat;

public class AccessControlSteps {

    private Response response;

    @When("an anonymous client sends a GET request to {string}")
    public void anonymousGet(String path) {
        response = Harness.anonymous().get(path);
    }

    @When("a client with a forged bearer token sends a GET request to {string}")
    public void forgedTokenGet(String path) {
        response = Harness.anonymous()
                .header("Authorization", "Bearer forged." + ApiSupport.letters(16) + ".signature")
                .get(path);
    }

    @Then("the unauthenticated call is rejected with status 401 or 403")
    public void rejectedUnauthorized() {
        assertThat(response.statusCode()).as("response body: %s", response.asString()).isIn(401, 403);
    }
}
