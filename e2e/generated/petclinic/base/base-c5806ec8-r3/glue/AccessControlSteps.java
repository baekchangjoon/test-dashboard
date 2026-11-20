package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

public class AccessControlSteps {

    private Response response;

    @When("an anonymous client sends a {word} request to {string}")
    public void anAnonymousClientSendsARequestTo(String method, String path) {
        if ("GET".equalsIgnoreCase(method)) {
            response = Harness.anonymous().get(path);
        } else {
            response = Harness.anonymous().contentType("application/json").body("{}").request(method, path);
        }
    }

    @When("a client with an invalid bearer token lists the reservations")
    public void aClientWithAnInvalidBearerTokenListsTheReservations() {
        response = Harness.anonymous().header("Authorization", "Bearer invalid-token-" + ApiSupport.suffix())
                .get("/api/reservations");
    }

    @Then("the access control response is unauthorized or forbidden")
    public void theAccessControlResponseIsUnauthorizedOrForbidden() {
        assertThat(response.statusCode()).as("response: %s", response.asString()).isIn(401, 403);
    }
}
