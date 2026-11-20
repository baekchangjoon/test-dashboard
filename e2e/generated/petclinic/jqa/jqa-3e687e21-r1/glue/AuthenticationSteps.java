package glue;

import glue.support.ApiData;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.HashMap;
import java.util.Map;
import td.harness.Harness;

import static org.assertj.core.api.Assertions.assertThat;

public class AuthenticationSteps {

    private Response response;

    private Response login(String username, String password) {
        Map<String, Object> body = new HashMap<>();
        body.put("username", username);
        body.put("password", password);
        return Harness.anonymous().contentType("application/json").body(body).post("/api/auth/login");
    }

    @When("the client logs in with an unknown username and a random password")
    public void loginUnknownUser() {
        response = login("nouser" + ApiData.suffix(), "pw" + ApiData.suffix());
    }

    @When("the client logs in as {string} with a random wrong password")
    public void loginWrongPassword(String username) {
        response = login(username, "wrong" + ApiData.suffix());
    }

    @Then("the login attempt is rejected with a client error")
    public void loginRejected() {
        assertThat(response.statusCode()).isBetween(400, 499);
    }

    @When("an anonymous client sends GET to {string}")
    public void anonymousGet(String path) {
        response = Harness.anonymous().get(path);
    }

    @When("an anonymous client submits a boarding reservation")
    public void anonymousCreateReservation() {
        response = Harness.anonymous().contentType("application/json").body(ApiData.reservationBody()).post("/api/reservations");
    }

    @Then("the anonymous request is denied")
    public void anonymousDenied() {
        assertThat(response.statusCode()).isIn(401, 403);
    }
}
