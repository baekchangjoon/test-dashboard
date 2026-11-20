package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
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

    @When("an anonymous caller sends GET to {string}")
    public void anonymousGet(String path) {
        response = Harness.anonymous().get(path);
    }

    @When("an anonymous caller tries to book a boarding reservation")
    public void anonymousBooking() {
        response = Harness.anonymous().contentType("application/json").body(ApiSupport.randomReservation(2))
                .post("/api/reservations");
    }

    @When("an anonymous caller logs in as an unknown random user")
    public void loginUnknownUser() {
        response = login(ApiSupport.uniqueName("nouser"), ApiSupport.uniqueName("pw"));
    }

    @When("an anonymous caller logs in as {string} with a random wrong password")
    public void loginWrongPassword(String username) {
        response = login(username, ApiSupport.uniqueName("wrong") + ApiSupport.randomDigits(6));
    }

    @When("an anonymous caller asks to validate the token {string}")
    public void validateToken(String token) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("token", token);
        response = Harness.anonymous().contentType("application/json").body(body).post("/api/auth/validate");
    }

    @Then("the access control response status is {int} or {int}")
    public void statusIsOneOf(int first, int second) {
        assertThat(response.statusCode()).as("body: %s", ApiSupport.text(response)).isIn(first, second);
    }

    @Then("the access control response is a client error")
    public void responseIsClientError() {
        assertThat(ApiSupport.isClientError(response.statusCode()))
                .as("status %s, body: %s", response.statusCode(), ApiSupport.text(response)).isTrue();
    }

    @Then("the access control validation does not succeed")
    public void validationDoesNotSucceed() {
        int status = response.statusCode();
        String body = ApiSupport.text(response).toLowerCase();
        assertThat(status >= 400 || !body.contains("true"))
                .as("status %s, body: %s", status, body).isTrue();
    }
}
