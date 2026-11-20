package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.LinkedHashMap;
import java.util.Map;
import td.harness.Harness;

public class OwnerManagementSteps {

    private Map<String, Object> owner;
    private String ownerId;
    private String changedCity;
    private Response response;
    private Response fetched;

    @When("all owners are requested")
    public void allOwnersAreRequested() {
        response = Harness.authed().get("/api/owners");
    }

    @Then("the owners request responds with status {int}")
    public void theOwnersRequestRespondsWithStatus(int status) {
        assertThat(response.statusCode()).as("response: " + response.asString()).isEqualTo(status);
    }

    @Given("a new owner with unique contact details")
    public void aNewOwnerWithUniqueContactDetails() {
        owner = new LinkedHashMap<>();
        owner.put("address", "1 Test Street " + ApiSupport.letters(6));
        owner.put("city", "City" + ApiSupport.letters(6));
        owner.put("telephone", ApiSupport.digits(10));
    }

    @When("the new owner is registered")
    public void theNewOwnerIsRegistered() {
        response = Harness.authed().contentType("application/json").body(owner).post("/api/owners");
        ownerId = ApiSupport.extractId(response);
    }

    @Then("the owner registration succeeds with an id")
    public void theOwnerRegistrationSucceedsWithAnId() {
        assertThat(response.statusCode()).as("response: " + response.asString()).isBetween(200, 299);
        assertThat(ownerId).as("created owner id").isNotNull().isNotBlank();
    }

    @When("the registered owner is fetched by id")
    public void theRegisteredOwnerIsFetchedById() {
        fetched = Harness.authed().get("/api/owners/" + ownerId);
    }

    @Then("the fetched owner shows the registered address, city and telephone")
    public void theFetchedOwnerShowsTheRegisteredValues() {
        assertThat(fetched.statusCode()).isEqualTo(200);
        assertThat(fetched.jsonPath().getString("address")).isEqualTo(owner.get("address"));
        assertThat(fetched.jsonPath().getString("city")).isEqualTo(owner.get("city"));
        assertThat(fetched.jsonPath().getString("telephone")).isEqualTo(owner.get("telephone"));
    }

    @When("the registered owner city is changed to a unique value")
    public void theRegisteredOwnerCityIsChanged() {
        changedCity = "Town" + ApiSupport.letters(6);
        Map<String, Object> payload = new LinkedHashMap<>(owner);
        payload.put("city", changedCity);
        response = Harness.authed().contentType("application/json").body(payload).put("/api/owners/" + ownerId);
    }

    @Then("the owner update succeeds")
    public void theOwnerUpdateSucceeds() {
        assertThat(response.statusCode()).as("response: " + response.asString()).isBetween(200, 299);
    }

    @Then("the fetched owner shows the changed city")
    public void theFetchedOwnerShowsTheChangedCity() {
        assertThat(fetched.statusCode()).isEqualTo(200);
        assertThat(fetched.jsonPath().getString("city")).isEqualTo(changedCity);
    }
}
