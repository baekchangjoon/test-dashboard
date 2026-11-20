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

    private Response response;
    private Map<String, Object> ownerBody;
    private String ownerId;
    private String newCity;

    private Response readOwner() {
        assertThat(ownerId).as("id of the registered owner").isNotBlank();
        return Harness.authed().get("/api/owners/" + ownerId);
    }

    @Given("a new owner with a unique last name is registered")
    public void ownerIsRegistered() {
        ownerBody = ApiSupport.randomOwner();
        Response created = Harness.authed().contentType("application/json").body(ownerBody).post("/api/owners");
        assertThat(created.statusCode()).as("owner creation status, body: %s", ApiSupport.text(created)).isIn(200, 201);
        ownerId = ApiSupport.extractId(created);
        assertThat(ownerId).as("id of the registered owner").isNotBlank();
    }

    @When("the owner client reads the registered owner")
    public void readsRegisteredOwner() {
        response = readOwner();
    }

    @Then("the owner response shows the registered names, address, city and telephone")
    public void showsRegisteredFields() {
        for (String key : new String[] {"firstName", "lastName", "address", "city", "telephone"}) {
            assertThat(ApiSupport.fieldText(response, key)).as(key).isEqualTo(String.valueOf(ownerBody.get(key)));
        }
    }

    @When("the owner client lists all owners")
    public void listsAllOwners() {
        response = Harness.authed().get("/api/owners");
    }

    @Then("the owner response mentions the registered last name")
    public void mentionsLastName() {
        assertThat(ApiSupport.text(response)).contains(String.valueOf(ownerBody.get("lastName")));
    }

    @When("the owner client changes the city of the registered owner to a new unique city")
    public void changesCity() {
        newCity = ApiSupport.uniqueName("Town");
        Map<String, Object> body = new LinkedHashMap<>(ownerBody);
        body.put("city", newCity);
        response = Harness.authed().contentType("application/json").body(body).put("/api/owners/" + ownerId);
    }

    @Then("reading the registered owner shows the new city")
    public void readingShowsNewCity() {
        Response read = readOwner();
        assertThat(read.statusCode()).isEqualTo(200);
        assertThat(ApiSupport.fieldText(read, "city")).isEqualTo(newCity);
    }

    @When("the owner client reads owner id {int}")
    public void readsOwnerById(int id) {
        response = Harness.authed().get("/api/owners/" + id);
    }

    @When("the owner client registers an owner with invalid data of kind {string}")
    public void registersInvalidOwner(String kind) {
        Map<String, Object> body = ApiSupport.randomOwner();
        switch (kind) {
            case "blank-first-name":
                body.put("firstName", "");
                break;
            case "blank-last-name":
                body.put("lastName", "");
                break;
            case "blank-city":
                body.put("city", "");
                break;
            case "non-numeric-telephone":
                body.put("telephone", "not-a-phone");
                break;
            default:
                throw new IllegalArgumentException("Unknown invalid owner kind: " + kind);
        }
        response = Harness.authed().contentType("application/json").body(body).post("/api/owners");
    }

    @Then("the owner response status is {int}")
    public void ownerStatusIs(int status) {
        assertThat(response.statusCode()).as("body: %s", ApiSupport.text(response)).isEqualTo(status);
    }

    @Then("the owner response is successful")
    public void ownerResponseSuccessful() {
        assertThat(ApiSupport.isSuccess(response.statusCode()))
                .as("status %s, body: %s", response.statusCode(), ApiSupport.text(response)).isTrue();
    }

    @Then("the owner response is a client error")
    public void ownerResponseClientError() {
        assertThat(ApiSupport.isClientError(response.statusCode()))
                .as("status %s, body: %s", response.statusCode(), ApiSupport.text(response)).isTrue();
    }
}
