package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiData;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.LinkedHashMap;
import java.util.Map;
import td.harness.Harness;

public class AuthenticationSteps {
    private Response response;

    private Response login(String username, String password) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("username", username);
        body.put("password", password);
        return Harness.anonymous().contentType("application/json").body(body).post("/api/auth/login");
    }

    @When("a login is attempted with a random unknown username")
    public void unknownLogin() {
        response = login("nouser" + ApiData.letters(10), "wrong" + ApiData.letters(10));
    }

    @When("a login is attempted with blank credentials")
    public void blankLogin() {
        response = login("", "");
    }

    @Then("the authentication response is a client error")
    public void clientError() {
        assertThat(response.statusCode()).as(response.asString()).isBetween(400, 499);
    }

    @When("the current harness session token is validated")
    public void validateToken() {
        response = Harness.authed().post("/api/auth/validate");
    }

    @Then("the authentication response is successful")
    public void successful() {
        assertThat(response.statusCode()).as(response.asString()).isBetween(200, 299);
    }

    @When("an anonymous client sends GET {string}")
    public void anonymousGet(String path) {
        response = Harness.anonymous().get(path);
    }

    @When("a client sends GET {string} with a forged bearer token")
    public void forgedToken(String path) {
        response = Harness.anonymous().header("Authorization", "Bearer forged." + ApiData.letters(16) + ".token").get(path);
    }

    @Then("access to the protected endpoint is denied with status 401 or 403")
    public void denied() {
        assertThat(response.statusCode()).as(response.asString()).isIn(401, 403);
    }
}
