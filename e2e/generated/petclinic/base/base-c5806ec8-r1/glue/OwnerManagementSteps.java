package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.HashMap;
import java.util.Map;
import td.harness.Harness;

public class OwnerManagementSteps {

    private Response lastResponse;
    private String ownerId;
    private String expectedCity;
    private Map<String, Object> ownerBody;

    @When("the client lists all owners")
    public void listOwners() {
        lastResponse = Harness.authed().get("/api/owners");
    }

    @Given("a new owner has been registered with a unique city")
    public void registerOwner() {
        String s = ApiSupport.suffix();
        ownerBody = new HashMap<>();
        ownerBody.put("address", "Street " + s);
        expectedCity = "City" + s;
        ownerBody.put("city", expectedCity);
        ownerBody.put("telephone", ApiSupport.randomDigits(10));
        Response response = Harness.authed().contentType("application/json").body(ownerBody).post("/api/owners");
        assertThat(response.statusCode()).as("create status, body: %s", response.asString()).isBetween(200, 299);
        ownerId = ApiSupport.extractId(response);
        assertThat(ownerId).as("created owner id").isNotBlank();
    }

    @When("the client fetches the registered owner")
    public void fetchOwner() {
        lastResponse = Harness.authed().get("/api/owners/" + ownerId);
    }

    @When("the client changes the city of the registered owner")
    public void changeCity() {
        Map<String, Object> updated = new HashMap<>(ownerBody);
        expectedCity = "NewCity" + ApiSupport.suffix();
        updated.put("city", expectedCity);
        lastResponse = Harness.authed().contentType("application/json").body(updated).put("/api/owners/" + ownerId);
    }

    @When("the client fetches an owner with an unknown id")
    public void fetchUnknownOwner() {
        lastResponse = Harness.authed().get("/api/owners/" + ApiSupport.UNKNOWN_ID);
    }

    @Then("the owner response has status {int}")
    public void hasStatus(int status) {
        assertThat(lastResponse.statusCode()).as("body: %s", lastResponse.asString()).isEqualTo(status);
    }

    @Then("the owner update is successful")
    public void updateSuccessful() {
        assertThat(lastResponse.statusCode()).as("body: %s", lastResponse.asString()).isBetween(200, 299);
    }

    @Then("the fetched owner shows the expected city")
    public void showsCity() {
        assertThat(lastResponse.jsonPath().getString("city")).isEqualTo(expectedCity);
    }

    @Then("the owner response is a client error")
    public void isClientError() {
        assertThat(lastResponse.statusCode()).as("body: %s", lastResponse.asString()).isBetween(400, 499);
    }
}
