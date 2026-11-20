package glue;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

public class OwnerManagementSteps {

    private Map<String, Object> body;
    private String ownerId;
    private String changedCity;
    private Response response;

    @When("the owner client requests the owner list")
    public void requestList() {
        response = Harness.authed().get("/api/owners");
    }

    @Given("a new owner has been registered through the owner API")
    public void registerOwner() {
        body = ApiSupport.ownerBody();
        Response created = Harness.authed().contentType("application/json").body(body).post("/api/owners");
        assertThat(created.statusCode()).as("create status, body: %s", created.asString()).isBetween(200, 299);
        ownerId = ApiSupport.extractId(created);
        assertThat(ownerId).as("created owner id").isNotBlank();
    }

    @When("the owner client fetches the registered owner")
    public void fetchOwner() {
        response = Harness.authed().get("/api/owners/" + ownerId);
    }

    @When("the owner client changes the city of the registered owner")
    public void changeCity() {
        Map<String, Object> update = new HashMap<>(body);
        changedCity = "Moved" + ApiSupport.suffix();
        update.put("city", changedCity);
        response = Harness.authed().contentType("application/json").body(update).put("/api/owners/" + ownerId);
    }

    @Then("the owner response status is {int}")
    public void statusIs(int expected) {
        assertThat(response.statusCode()).as("status, body: %s", response.asString()).isEqualTo(expected);
    }

    @Then("the owner response status is successful")
    public void statusIsSuccessful() {
        assertThat(response.statusCode()).as("status, body: %s", response.asString()).isBetween(200, 299);
    }

    @Then("the fetched owner has the submitted address, city and telephone")
    public void hasSubmittedFields() {
        assertThat(response.jsonPath().getString("address")).isEqualTo(body.get("address"));
        assertThat(response.jsonPath().getString("city")).isEqualTo(body.get("city"));
        assertThat(response.jsonPath().getString("telephone")).isEqualTo(body.get("telephone"));
    }

    @Then("the fetched owner shows the changed city")
    public void showsChangedCity() {
        assertThat(response.jsonPath().getString("city")).isEqualTo(changedCity);
    }
}
